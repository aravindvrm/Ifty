from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import json
from typing import Any
from urllib.parse import quote, urlparse
from uuid import uuid4

import requests
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.alerts.events import collect_watchlist_events
from app.config import Settings


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def _normalize_flag(value: object, *, default: int = 1) -> int:
    if value is None:
        return int(1 if default else 0)
    if isinstance(value, bool):
        return int(1 if value else 0)
    try:
        num = int(value)
    except (TypeError, ValueError):
        num = default
    return 1 if num else 0


def _normalize_secret(value: object | None) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    return raw[:256]


def _normalize_endpoint_url(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("endpoint_url is required")
    if len(raw) > 500:
        raise ValueError("endpoint_url is too long")
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("endpoint_url must use http or https")
    if not parsed.netloc:
        raise ValueError("endpoint_url host is required")
    return raw


def ensure_alert_schema(db: Session) -> None:
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS webhook_subscriptions (
              webhook_subscription_id TEXT PRIMARY KEY,
              owner_user_id TEXT NOT NULL,
              watchlist_id TEXT NOT NULL REFERENCES watchlists (watchlist_id) ON DELETE CASCADE,
              endpoint_url TEXT NOT NULL,
              endpoint_secret TEXT,
              include_13dg INTEGER NOT NULL DEFAULT 1,
              include_insider INTEGER NOT NULL DEFAULT 1,
              is_active INTEGER NOT NULL DEFAULT 1,
              created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_webhook_subscriptions_owner
            ON webhook_subscriptions (owner_user_id, created_at DESC)
            """
        )
    )
    db.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ux_webhook_subscriptions_owner_watchlist_endpoint
            ON webhook_subscriptions (owner_user_id, watchlist_id, endpoint_url)
            """
        )
    )
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS webhook_delivery_log (
              webhook_delivery_id TEXT PRIMARY KEY,
              webhook_subscription_id TEXT NOT NULL REFERENCES webhook_subscriptions (webhook_subscription_id) ON DELETE CASCADE,
              owner_user_id TEXT NOT NULL,
              event_source TEXT NOT NULL,
              event_key TEXT NOT NULL,
              event_ts TEXT,
              status TEXT NOT NULL,
              provider_message_id TEXT,
              http_status INTEGER,
              error_text TEXT,
              payload_json TEXT,
              created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
              delivered_at TIMESTAMP
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_webhook_delivery_owner_ts
            ON webhook_delivery_log (owner_user_id, created_at DESC)
            """
        )
    )
    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_webhook_delivery_event
            ON webhook_delivery_log (webhook_subscription_id, event_source, event_key, status, created_at DESC)
            """
        )
    )


def _assert_watchlist_owner(db: Session, *, watchlist_id: str, owner_user_id: str) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            SELECT watchlist_id, owner_user_id, watchlist_type, name
            FROM watchlists
            WHERE watchlist_id = :watchlist_id AND owner_user_id = :owner_user_id
            LIMIT 1
            """
        ),
        {"watchlist_id": watchlist_id, "owner_user_id": owner_user_id},
    ).mappings().first()
    if not row:
        raise ValueError("Watchlist not found")
    return dict(row)


def list_subscriptions(db: Session, *, owner_user_id: str) -> dict[str, Any]:
    ensure_alert_schema(db)
    rows = db.execute(
        text(
            """
            SELECT
              s.webhook_subscription_id,
              s.owner_user_id,
              s.watchlist_id,
              w.name AS watchlist_name,
              s.endpoint_url,
              s.include_13dg,
              s.include_insider,
              s.is_active,
              s.created_at,
              s.updated_at
            FROM webhook_subscriptions s
            JOIN watchlists w ON w.watchlist_id = s.watchlist_id
            WHERE s.owner_user_id = :owner_user_id
            ORDER BY s.created_at DESC, s.webhook_subscription_id DESC
            """
        ),
        {"owner_user_id": owner_user_id},
    ).mappings().all()
    return {
        "owner_user_id": owner_user_id,
        "rows": [
            {
                "webhook_subscription_id": str(row["webhook_subscription_id"]),
                "owner_user_id": str(row["owner_user_id"]),
                "watchlist_id": str(row["watchlist_id"]),
                "watchlist_name": str(row.get("watchlist_name") or ""),
                "endpoint_url": str(row["endpoint_url"]),
                "include_13dg": int(row.get("include_13dg") or 0),
                "include_insider": int(row.get("include_insider") or 0),
                "is_active": int(row.get("is_active") or 0),
                "created_at": str(row.get("created_at") or ""),
                "updated_at": str(row.get("updated_at") or ""),
            }
            for row in rows
        ],
    }


def create_subscription(
    db: Session,
    *,
    owner_user_id: str,
    watchlist_id: str,
    endpoint_url: str,
    endpoint_secret: str | None,
    include_13dg: object,
    include_insider: object,
    is_active: object,
) -> dict[str, Any]:
    ensure_alert_schema(db)
    _assert_watchlist_owner(db, watchlist_id=watchlist_id, owner_user_id=owner_user_id)

    normalized_endpoint_url = _normalize_endpoint_url(endpoint_url)
    normalized_secret = _normalize_secret(endpoint_secret)
    include_13dg_n = _normalize_flag(include_13dg, default=1)
    include_insider_n = _normalize_flag(include_insider, default=1)
    is_active_n = _normalize_flag(is_active, default=1)

    dup = db.execute(
        text(
            """
            SELECT webhook_subscription_id
            FROM webhook_subscriptions
            WHERE owner_user_id = :owner_user_id
              AND watchlist_id = :watchlist_id
              AND endpoint_url = :endpoint_url
            LIMIT 1
            """
        ),
        {
            "owner_user_id": owner_user_id,
            "watchlist_id": watchlist_id,
            "endpoint_url": normalized_endpoint_url,
        },
    ).first()
    if dup:
        raise ValueError("Subscription already exists for this watchlist + endpoint")

    webhook_subscription_id = _new_id("whsub")
    db.execute(
        text(
            """
            INSERT INTO webhook_subscriptions (
              webhook_subscription_id,
              owner_user_id,
              watchlist_id,
              endpoint_url,
              endpoint_secret,
              include_13dg,
              include_insider,
              is_active
            ) VALUES (
              :webhook_subscription_id,
              :owner_user_id,
              :watchlist_id,
              :endpoint_url,
              :endpoint_secret,
              :include_13dg,
              :include_insider,
              :is_active
            )
            """
        ),
        {
            "webhook_subscription_id": webhook_subscription_id,
            "owner_user_id": owner_user_id,
            "watchlist_id": watchlist_id,
            "endpoint_url": normalized_endpoint_url,
            "endpoint_secret": normalized_secret,
            "include_13dg": include_13dg_n,
            "include_insider": include_insider_n,
            "is_active": is_active_n,
        },
    )
    db.commit()
    return {
        "webhook_subscription_id": webhook_subscription_id,
        "owner_user_id": owner_user_id,
        "watchlist_id": watchlist_id,
        "endpoint_url": normalized_endpoint_url,
        "include_13dg": include_13dg_n,
        "include_insider": include_insider_n,
        "is_active": is_active_n,
    }


def _assert_subscription_owner(
    db: Session,
    *,
    webhook_subscription_id: str,
    owner_user_id: str,
) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            SELECT
              webhook_subscription_id,
              owner_user_id,
              watchlist_id,
              endpoint_url,
              endpoint_secret,
              include_13dg,
              include_insider,
              is_active
            FROM webhook_subscriptions
            WHERE webhook_subscription_id = :webhook_subscription_id
              AND owner_user_id = :owner_user_id
            LIMIT 1
            """
        ),
        {
            "webhook_subscription_id": webhook_subscription_id,
            "owner_user_id": owner_user_id,
        },
    ).mappings().first()
    if not row:
        raise ValueError("Subscription not found")
    return dict(row)


def update_subscription(
    db: Session,
    *,
    owner_user_id: str,
    webhook_subscription_id: str,
    endpoint_url: str | None,
    endpoint_secret: str | None,
    include_13dg: object | None,
    include_insider: object | None,
    is_active: object | None,
) -> dict[str, Any]:
    ensure_alert_schema(db)
    current = _assert_subscription_owner(
        db,
        webhook_subscription_id=webhook_subscription_id,
        owner_user_id=owner_user_id,
    )

    normalized_endpoint_url = (
        _normalize_endpoint_url(endpoint_url) if endpoint_url is not None else str(current["endpoint_url"])
    )
    normalized_secret = (
        _normalize_secret(endpoint_secret) if endpoint_secret is not None else _normalize_secret(current.get("endpoint_secret"))
    )
    include_13dg_n = (
        _normalize_flag(include_13dg, default=int(current.get("include_13dg") or 0))
        if include_13dg is not None
        else int(current.get("include_13dg") or 0)
    )
    include_insider_n = (
        _normalize_flag(include_insider, default=int(current.get("include_insider") or 0))
        if include_insider is not None
        else int(current.get("include_insider") or 0)
    )
    is_active_n = (
        _normalize_flag(is_active, default=int(current.get("is_active") or 0))
        if is_active is not None
        else int(current.get("is_active") or 0)
    )

    db.execute(
        text(
            """
            UPDATE webhook_subscriptions
            SET
              endpoint_url = :endpoint_url,
              endpoint_secret = :endpoint_secret,
              include_13dg = :include_13dg,
              include_insider = :include_insider,
              is_active = :is_active,
              updated_at = CURRENT_TIMESTAMP
            WHERE webhook_subscription_id = :webhook_subscription_id
              AND owner_user_id = :owner_user_id
            """
        ),
        {
            "webhook_subscription_id": webhook_subscription_id,
            "owner_user_id": owner_user_id,
            "endpoint_url": normalized_endpoint_url,
            "endpoint_secret": normalized_secret,
            "include_13dg": include_13dg_n,
            "include_insider": include_insider_n,
            "is_active": is_active_n,
        },
    )
    db.commit()
    return {
        "webhook_subscription_id": webhook_subscription_id,
        "owner_user_id": owner_user_id,
        "watchlist_id": str(current["watchlist_id"]),
        "endpoint_url": normalized_endpoint_url,
        "include_13dg": include_13dg_n,
        "include_insider": include_insider_n,
        "is_active": is_active_n,
    }


def delete_subscription(
    db: Session,
    *,
    owner_user_id: str,
    webhook_subscription_id: str,
) -> dict[str, object]:
    ensure_alert_schema(db)
    _assert_subscription_owner(
        db,
        webhook_subscription_id=webhook_subscription_id,
        owner_user_id=owner_user_id,
    )
    db.execute(
        text(
            """
            DELETE FROM webhook_subscriptions
            WHERE webhook_subscription_id = :webhook_subscription_id
              AND owner_user_id = :owner_user_id
            """
        ),
        {
            "webhook_subscription_id": webhook_subscription_id,
            "owner_user_id": owner_user_id,
        },
    )
    db.commit()
    return {"ok": True}


def list_deliveries(
    db: Session,
    *,
    owner_user_id: str,
    webhook_subscription_id: str | None = None,
    limit_n: int = 100,
) -> dict[str, Any]:
    ensure_alert_schema(db)
    where = ["owner_user_id = :owner_user_id"]
    params: dict[str, object] = {"owner_user_id": owner_user_id, "limit_n": max(1, min(500, int(limit_n)))}
    if webhook_subscription_id:
        where.append("webhook_subscription_id = :webhook_subscription_id")
        params["webhook_subscription_id"] = webhook_subscription_id
    rows = db.execute(
        text(
            f"""
            SELECT
              webhook_delivery_id,
              webhook_subscription_id,
              owner_user_id,
              event_source,
              event_key,
              event_ts,
              status,
              provider_message_id,
              http_status,
              error_text,
              created_at,
              delivered_at
            FROM webhook_delivery_log
            WHERE {' AND '.join(where)}
            ORDER BY created_at DESC, webhook_delivery_id DESC
            LIMIT :limit_n
            """
        ),
        params,
    ).mappings().all()
    return {
        "owner_user_id": owner_user_id,
        "rows": [dict(row) for row in rows],
    }


def _build_signed_envelope(event_payload: dict[str, Any], endpoint_secret: str | None) -> tuple[str, str | None, str]:
    sent_at = datetime.now(UTC).isoformat()
    payload = dict(event_payload)
    payload["sent_at"] = sent_at
    raw_json = json.dumps(payload, default=str, separators=(",", ":"))
    if not endpoint_secret:
        return raw_json, None, sent_at
    signature = hmac.new(
        endpoint_secret.encode("utf-8"),
        f"{sent_at}.{raw_json}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    payload["signature"] = {
        "algorithm": "hmac-sha256",
        "timestamp": sent_at,
        "value": signature,
    }
    signed_json = json.dumps(payload, default=str, separators=(",", ":"))
    return signed_json, signature, sent_at


def _send_webhook(
    *,
    settings: Settings,
    endpoint_url: str,
    endpoint_secret: str | None,
    event_payload: dict[str, Any],
) -> dict[str, Any]:
    payload_json, signature, sent_at = _build_signed_envelope(event_payload, endpoint_secret)
    mode = str(settings.alerts_webhook_mode or "qstash").strip().lower()
    timeout_seconds = max(1.0, float(settings.alerts_request_timeout_seconds))
    if mode == "qstash":
        token = str(settings.alerts_qstash_token or "").strip()
        if not token:
            return {
                "status": "failed",
                "http_status": None,
                "provider_message_id": None,
                "error_text": "ALERTS_QSTASH_TOKEN is missing",
                "payload_json": payload_json,
                "delivered_at": None,
            }
        base_url = str(settings.alerts_qstash_base_url or "https://qstash.upstash.io").strip().rstrip("/")
        target = quote(endpoint_url, safe="")
        publish_url = f"{base_url}/v2/publish/{target}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        retries = max(0, int(settings.alerts_qstash_retries))
        headers["Upstash-Retries"] = str(retries)
        try:
            response = requests.post(
                publish_url,
                data=payload_json,
                headers=headers,
                timeout=timeout_seconds,
            )
        except requests.RequestException as exc:
            return {
                "status": "failed",
                "http_status": None,
                "provider_message_id": None,
                "error_text": str(exc),
                "payload_json": payload_json,
                "delivered_at": None,
            }
        provider_message_id: str | None = None
        try:
            body = response.json()
            if isinstance(body, dict):
                msg_id = body.get("messageId") or body.get("message_id")
                if msg_id:
                    provider_message_id = str(msg_id)
        except ValueError:
            provider_message_id = None
        if response.status_code >= 400:
            return {
                "status": "failed",
                "http_status": int(response.status_code),
                "provider_message_id": provider_message_id,
                "error_text": (response.text or "")[:600],
                "payload_json": payload_json,
                "delivered_at": None,
            }
        return {
            "status": "queued",
            "http_status": int(response.status_code),
            "provider_message_id": provider_message_id,
            "error_text": None,
            "payload_json": payload_json,
            "delivered_at": sent_at,
            "signature": signature,
        }

    # Direct mode for local testing without queue provider.
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Ifty-Alerts/1.0",
        "X-Ifty-Timestamp": sent_at,
    }
    if signature:
        headers["X-Ifty-Signature"] = signature
    try:
        response = requests.post(endpoint_url, data=payload_json, headers=headers, timeout=timeout_seconds)
    except requests.RequestException as exc:
        return {
            "status": "failed",
            "http_status": None,
            "provider_message_id": None,
            "error_text": str(exc),
            "payload_json": payload_json,
            "delivered_at": None,
        }
    if response.status_code >= 400:
        return {
            "status": "failed",
            "http_status": int(response.status_code),
            "provider_message_id": None,
            "error_text": (response.text or "")[:600],
            "payload_json": payload_json,
            "delivered_at": None,
        }
    return {
        "status": "sent",
        "http_status": int(response.status_code),
        "provider_message_id": None,
        "error_text": None,
        "payload_json": payload_json,
        "delivered_at": sent_at,
        "signature": signature,
    }


def _already_sent(
    db: Session,
    *,
    webhook_subscription_id: str,
    event_source: str,
    event_key: str,
) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1
            FROM webhook_delivery_log
            WHERE webhook_subscription_id = :webhook_subscription_id
              AND event_source = :event_source
              AND event_key = :event_key
              AND status IN ('queued', 'sent')
            LIMIT 1
            """
        ),
        {
            "webhook_subscription_id": webhook_subscription_id,
            "event_source": event_source,
            "event_key": event_key,
        },
    ).first()
    return bool(row)


def _insert_delivery_log(
    db: Session,
    *,
    webhook_subscription_id: str,
    owner_user_id: str,
    event_source: str,
    event_key: str,
    event_ts: str | None,
    status: str,
    provider_message_id: str | None,
    http_status: int | None,
    error_text: str | None,
    payload_json: str | None,
    delivered_at: str | None,
) -> None:
    db.execute(
        text(
            """
            INSERT INTO webhook_delivery_log (
              webhook_delivery_id,
              webhook_subscription_id,
              owner_user_id,
              event_source,
              event_key,
              event_ts,
              status,
              provider_message_id,
              http_status,
              error_text,
              payload_json,
              delivered_at
            ) VALUES (
              :webhook_delivery_id,
              :webhook_subscription_id,
              :owner_user_id,
              :event_source,
              :event_key,
              :event_ts,
              :status,
              :provider_message_id,
              :http_status,
              :error_text,
              :payload_json,
              :delivered_at
            )
            """
        ),
        {
            "webhook_delivery_id": _new_id("whlog"),
            "webhook_subscription_id": webhook_subscription_id,
            "owner_user_id": owner_user_id,
            "event_source": event_source,
            "event_key": event_key,
            "event_ts": event_ts,
            "status": status,
            "provider_message_id": provider_message_id,
            "http_status": http_status,
            "error_text": (error_text or None),
            "payload_json": payload_json,
            "delivered_at": delivered_at,
        },
    )


def dispatch_subscriptions(
    db: Session,
    *,
    settings: Settings,
    owner_user_id: str | None,
    lookback_hours: int,
    max_events: int,
    only_subscription_id: str | None = None,
) -> dict[str, Any]:
    ensure_alert_schema(db)
    if not settings.alerts_enabled:
        return {"ok": False, "message": "alerts_disabled"}

    lookback_hours_n = max(1, min(24 * 30, int(lookback_hours)))
    max_events_n = max(1, min(5000, int(max_events)))
    since_date = (datetime.now(UTC) - timedelta(hours=lookback_hours_n)).date()

    where = ["is_active = 1"]
    params: dict[str, object] = {}
    if owner_user_id:
        where.append("owner_user_id = :owner_user_id")
        params["owner_user_id"] = owner_user_id
    if only_subscription_id:
        where.append("webhook_subscription_id = :webhook_subscription_id")
        params["webhook_subscription_id"] = only_subscription_id

    subscriptions = db.execute(
        text(
            f"""
            SELECT
              webhook_subscription_id,
              owner_user_id,
              watchlist_id,
              endpoint_url,
              endpoint_secret,
              include_13dg,
              include_insider
            FROM webhook_subscriptions
            WHERE {' AND '.join(where)}
            ORDER BY created_at DESC
            """
        ),
        params,
    ).mappings().all()

    dispatched = 0
    skipped_duplicates = 0
    failed = 0
    inspected_events = 0
    for subscription in subscriptions:
        sid = str(subscription["webhook_subscription_id"])
        owner_id = str(subscription["owner_user_id"])
        endpoint_url = str(subscription["endpoint_url"])
        endpoint_secret = _normalize_secret(subscription.get("endpoint_secret"))
        include_13dg = bool(int(subscription.get("include_13dg") or 0))
        include_insider = bool(int(subscription.get("include_insider") or 0))

        events = collect_watchlist_events(
            db=db,
            owner_user_id=owner_id,
            since_date=since_date,
            include_13dg=include_13dg,
            include_insider=include_insider,
            only_watchlist_id=str(subscription["watchlist_id"]),
            limit_per_watchlist=max_events_n,
        )
        for event in events:
            inspected_events += 1
            if dispatched >= max_events_n:
                break
            event_source = str(event.get("event_source") or "").upper()
            event_key = str(event.get("event_key") or "").strip()
            if not event_source or not event_key:
                continue
            if _already_sent(
                db,
                webhook_subscription_id=sid,
                event_source=event_source,
                event_key=event_key,
            ):
                skipped_duplicates += 1
                continue

            payload = {
                "event_version": "2026-04-11.1",
                "webhook_subscription_id": sid,
                "owner_user_id": owner_id,
                "watchlist_id": event.get("watchlist_id"),
                "watchlist_name": event.get("watchlist_name"),
                "event_source": event_source,
                "event_key": event_key,
                "event_ts": event.get("event_ts"),
                "title": event.get("title"),
                "summary": event.get("summary"),
                "data": event,
            }
            send_result = _send_webhook(
                settings=settings,
                endpoint_url=endpoint_url,
                endpoint_secret=endpoint_secret,
                event_payload=payload,
            )
            status = str(send_result.get("status") or "failed")
            if status in {"queued", "sent"}:
                dispatched += 1
            else:
                failed += 1
            _insert_delivery_log(
                db,
                webhook_subscription_id=sid,
                owner_user_id=owner_id,
                event_source=event_source,
                event_key=event_key,
                event_ts=str(event.get("event_ts") or ""),
                status=status,
                provider_message_id=(
                    str(send_result["provider_message_id"])
                    if send_result.get("provider_message_id") is not None
                    else None
                ),
                http_status=(
                    int(send_result["http_status"])
                    if send_result.get("http_status") is not None
                    else None
                ),
                error_text=(
                    str(send_result["error_text"]) if send_result.get("error_text") else None
                ),
                payload_json=(
                    str(send_result["payload_json"])
                    if send_result.get("payload_json") is not None
                    else None
                ),
                delivered_at=(
                    str(send_result["delivered_at"])
                    if send_result.get("delivered_at") is not None
                    else None
                ),
            )
        if dispatched >= max_events_n:
            break
    db.commit()
    return {
        "ok": True,
        "owner_user_id": owner_user_id,
        "lookback_hours": lookback_hours_n,
        "subscriptions": len(subscriptions),
        "inspected_events": inspected_events,
        "dispatched": dispatched,
        "failed": failed,
        "skipped_duplicates": skipped_duplicates,
        "max_events": max_events_n,
    }


def send_subscription_test_event(
    db: Session,
    *,
    settings: Settings,
    owner_user_id: str,
    webhook_subscription_id: str,
) -> dict[str, Any]:
    ensure_alert_schema(db)
    subscription = _assert_subscription_owner(
        db,
        webhook_subscription_id=webhook_subscription_id,
        owner_user_id=owner_user_id,
    )
    payload = {
        "event_version": "2026-04-11.1",
        "webhook_subscription_id": webhook_subscription_id,
        "owner_user_id": owner_user_id,
        "watchlist_id": str(subscription["watchlist_id"]),
        "watchlist_name": "Test",
        "event_source": "TEST",
        "event_key": f"test:{uuid4().hex}",
        "event_ts": datetime.now(UTC).isoformat(),
        "title": "Ifty test webhook",
        "summary": "This is a test delivery from Ifty webhook alerts.",
        "data": {"kind": "test"},
    }
    send_result = _send_webhook(
        settings=settings,
        endpoint_url=str(subscription["endpoint_url"]),
        endpoint_secret=_normalize_secret(subscription.get("endpoint_secret")),
        event_payload=payload,
    )
    status = str(send_result.get("status") or "failed")
    _insert_delivery_log(
        db,
        webhook_subscription_id=webhook_subscription_id,
        owner_user_id=owner_user_id,
        event_source="TEST",
        event_key=str(payload["event_key"]),
        event_ts=str(payload["event_ts"]),
        status=status,
        provider_message_id=(
            str(send_result["provider_message_id"])
            if send_result.get("provider_message_id") is not None
            else None
        ),
        http_status=(
            int(send_result["http_status"])
            if send_result.get("http_status") is not None
            else None
        ),
        error_text=(str(send_result["error_text"]) if send_result.get("error_text") else None),
        payload_json=(str(send_result["payload_json"]) if send_result.get("payload_json") else None),
        delivered_at=(str(send_result["delivered_at"]) if send_result.get("delivered_at") else None),
    )
    db.commit()
    return {
        "ok": status in {"queued", "sent"},
        "status": status,
        "http_status": send_result.get("http_status"),
        "provider_message_id": send_result.get("provider_message_id"),
        "error_text": send_result.get("error_text"),
    }

