from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.ai.openai_compat import OpenAICompatClient
from app.alerts.events import collect_watchlist_events
from app.config import Settings


def _events_to_sources(events: list[dict[str, Any]], limit_n: int = 10) -> list[dict[str, str]]:
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for event in events:
        label = str(event.get("title") or event.get("event_key") or "Event").strip()
        sec_url = str(event.get("sec_url") or "").strip()
        source_path = str(event.get("source_path") or "").strip()
        key = sec_url or source_path or label
        if not key or key in seen:
            continue
        seen.add(key)
        row: dict[str, str] = {"label": label}
        if sec_url:
            row["url"] = sec_url
        elif source_path:
            row["path"] = source_path
        out.append(row)
        if len(out) >= max(1, limit_n):
            break
    return out


def _fallback_summary(
    *,
    days: int,
    events: list[dict[str, Any]],
) -> str:
    if not events:
        return f"No notable watchlist events were detected in the last {days} day(s)."
    by_source: dict[str, int] = {}
    for event in events:
        source = str(event.get("event_source") or "OTHER")
        by_source[source] = int(by_source.get(source, 0) + 1)
    parts = []
    for key in ["13DG", "INSIDER", "OTHER"]:
        count = by_source.get(key, 0)
        if count:
            parts.append(f"{count} {key} event{'s' if count != 1 else ''}")
    head = ", ".join(parts) if parts else f"{len(events)} events"
    top = events[0]
    top_title = str(top.get("title") or top.get("event_key") or "Top event")
    return f"In the last {days} day(s): {head}. Most recent: {top_title}."


def _ai_summary(
    *,
    settings: Settings,
    events: list[dict[str, Any]],
    days: int,
) -> str | None:
    if not settings.ai_enabled:
        return None
    if not settings.ai_base_url:
        return None
    if not events:
        return None

    compact_events: list[dict[str, Any]] = []
    for event in events[:20]:
        compact_events.append(
            {
                "ts": event.get("event_ts"),
                "source": event.get("event_source"),
                "title": event.get("title"),
                "summary": event.get("summary"),
                "ticker": event.get("ticker"),
                "watchlist": event.get("watchlist_name"),
                "sec_url": event.get("sec_url"),
            }
        )

    client = OpenAICompatClient(
        base_url=settings.ai_base_url,
        api_key=settings.ai_api_key,
        timeout_seconds=settings.ai_request_timeout_seconds,
    )
    prompt = (
        "Create a concise daily watchlist briefing from the structured events below.\n"
        "Output 2 short paragraphs max.\n"
        "Focus on: what changed, potential implications, and what to monitor.\n"
        "Do not invent any facts or numbers.\n"
        f"Window: last {days} day(s).\n\n"
        f"Events: {compact_events!r}"
    )
    response = client.chat_completions(
        {
            "model": settings.ai_model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are Ifty AI. Summarize events clearly and conservatively.",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": max(0.0, min(0.4, float(settings.ai_temperature))),
            "max_tokens": min(700, max(180, int(settings.ai_max_output_tokens))),
        }
    )
    choice = (response.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        text = content.strip()
        return text or None
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict):
                text = part.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
        if parts:
            return "\n".join(parts).strip()
    return None


def build_daily_briefing(
    db: Session,
    *,
    owner_user_id: str,
    settings: Settings,
    days: int = 1,
    max_events: int = 40,
) -> dict[str, Any]:
    days_n = max(1, min(30, int(days)))
    max_events_n = max(1, min(200, int(max_events)))
    since = (datetime.now(UTC) - timedelta(days=days_n)).date()
    events = collect_watchlist_events(
        db=db,
        owner_user_id=owner_user_id,
        since_date=since,
        include_13dg=True,
        include_insider=True,
        limit_per_watchlist=max_events_n,
    )[:max_events_n]

    ai_summary: str | None = None
    ai_error: str | None = None
    try:
        ai_summary = _ai_summary(settings=settings, events=events, days=days_n)
    except Exception as exc:  # noqa: BLE001
        ai_error = str(exc)

    summary = ai_summary or _fallback_summary(days=days_n, events=events)
    highlights = [
        {
            "title": str(event.get("title") or event.get("event_key") or "Event"),
            "summary": str(event.get("summary") or ""),
            "event_source": str(event.get("event_source") or ""),
            "event_ts": str(event.get("event_ts") or ""),
            "path": str(event.get("source_path") or ""),
            "sec_url": str(event.get("sec_url") or ""),
        }
        for event in events[:8]
    ]
    sources = _events_to_sources(events, limit_n=10)
    by_source: dict[str, int] = {}
    for event in events:
        key = str(event.get("event_source") or "OTHER")
        by_source[key] = int(by_source.get(key, 0) + 1)

    return {
        "owner_user_id": owner_user_id,
        "days": days_n,
        "generated_at": datetime.now(UTC).isoformat(),
        "summary": summary,
        "highlights": highlights,
        "sources": sources,
        "counts": {
            "events": len(events),
            "by_source": by_source,
        },
        "ai_used": bool(ai_summary),
        "ai_error": ai_error,
    }

