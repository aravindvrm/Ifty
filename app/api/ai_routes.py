from __future__ import annotations

from time import perf_counter
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.ai.openai_compat import OpenAICompatClient
from app.ai.service import AiChatService
from app.config import get_settings
from app.dependencies import get_db

router = APIRouter(prefix="/ai", tags=["ai"])


class AiChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(..., min_length=1, max_length=12000)


class AiChatRequest(BaseModel):
    messages: list[AiChatMessage] = Field(..., min_length=1, max_length=30)
    max_steps: int | None = Field(default=None, ge=1, le=12)
    include_trace: bool = Field(default=False)


class AiChatResponse(BaseModel):
    answer: str
    model: str
    used_tools: list[str]
    sources: list[dict[str, str]]
    sql_fallback_enabled: bool
    steps: int
    trace: list[dict[str, Any]] | None = None


def _normalize_ticker(value: object) -> str | None:
    ticker = str(value or "").strip().upper()
    if not ticker:
        return None
    if len(ticker) > 12:
        return None
    return ticker


def _normalize_manager_id(value: object) -> int | None:
    try:
        manager_id = int(value)
        if manager_id <= 0:
            return None
        return manager_id
    except (TypeError, ValueError):
        return None


def _build_sources_from_trace(trace: list[dict[str, Any]]) -> list[dict[str, str]]:
    sources: list[dict[str, str]] = []
    source_priorities: list[int] = []
    path_to_idx: dict[str, int] = {}
    label_to_idx: dict[str, int] = {}

    def push(label: str, path: str | None = None, priority: int = 10) -> None:
        clean_label = label.strip()
        clean_path = (path or "").strip()
        if not clean_label:
            return

        if clean_path:
            existing_idx = path_to_idx.get(clean_path)
            if existing_idx is not None:
                if priority > source_priorities[existing_idx]:
                    sources[existing_idx]["label"] = clean_label
                    source_priorities[existing_idx] = priority
                return
        else:
            existing_idx = label_to_idx.get(clean_label)
            if existing_idx is not None:
                if priority > source_priorities[existing_idx]:
                    source_priorities[existing_idx] = priority
                return

        row = {"label": clean_label}
        if clean_path:
            row["path"] = clean_path
        sources.append(row)
        source_priorities.append(priority)
        idx = len(sources) - 1
        if clean_path:
            path_to_idx[clean_path] = idx
        else:
            label_to_idx[clean_label] = idx

    for entry in trace:
        tool_name = str((entry or {}).get("tool") or "").strip()
        args = (entry or {}).get("arguments")
        result = (entry or {}).get("result")
        args = args if isinstance(args, dict) else {}
        result = result if isinstance(result, dict) else {}

        if tool_name == "security_snapshot":
            ticker = _normalize_ticker(result.get("ticker")) or _normalize_ticker(args.get("ticker"))
            if ticker:
                push(f"Security Snapshot: {ticker}", f"/security/{ticker}", priority=30)
            else:
                push("Security Snapshot", priority=30)
            continue

        if tool_name == "search_securities":
            rows = result.get("rows")
            if isinstance(rows, list):
                for row in rows[:3]:
                    if not isinstance(row, dict):
                        continue
                    ticker = _normalize_ticker(row.get("ticker"))
                    name = str(row.get("security_name") or row.get("issuer_name") or "").strip()
                    if ticker:
                        label = f"Security Match: {ticker}"
                        if name:
                            label = f"{label} ({name})"
                        push(label, f"/security/{ticker}", priority=10)
                    elif name:
                        push(f"Security Match: {name}", priority=10)
            continue

        if tool_name == "institution_snapshot":
            manager = result.get("manager")
            manager = manager if isinstance(manager, dict) else {}
            manager_id = _normalize_manager_id(manager.get("manager_id"))
            manager_name = str(manager.get("manager_name") or args.get("manager_key") or "").strip()
            if manager_id is not None:
                push(
                    f"Institution Snapshot: {manager_name or f'ID {manager_id}'}",
                    f"/institution/{manager_id}",
                    priority=30,
                )
            else:
                push(
                    f"Institution Snapshot: {manager_name}" if manager_name else "Institution Snapshot",
                    priority=30,
                )
            continue

        if tool_name == "search_institutions":
            rows = result.get("rows")
            if isinstance(rows, list):
                for row in rows[:3]:
                    if not isinstance(row, dict):
                        continue
                    manager_id = _normalize_manager_id(row.get("manager_id"))
                    manager_name = str(row.get("manager_name") or "").strip()
                    if manager_id is not None:
                        push(
                            f"Institution Match: {manager_name or f'ID {manager_id}'}",
                            f"/institution/{manager_id}",
                            priority=10,
                        )
                    elif manager_name:
                        push(f"Institution Match: {manager_name}", priority=10)
            continue

        if tool_name == "market_pulse":
            push("Market Pulse Overview", "/", priority=20)
            continue

        if tool_name == "recent_13dg_events":
            push("Recent 13D/G Events", "/feed", priority=20)
            rows = result.get("rows")
            if isinstance(rows, list):
                for row in rows[:2]:
                    if not isinstance(row, dict):
                        continue
                    ticker = _normalize_ticker(row.get("ticker"))
                    if ticker:
                        push(f"13D/G Security: {ticker}", f"/security/{ticker}", priority=15)
            continue

        if tool_name:
            push(f"Tool: {tool_name}", priority=1)

    if not sources:
        push("Ifty institutional database", priority=1)

    return sources[:8]


@router.post("/chat", response_model=AiChatResponse)
def ai_chat(
    payload: AiChatRequest,
    db: Session = Depends(get_db),
) -> AiChatResponse:
    settings = get_settings()
    endpoint = f"/ai/chat model={settings.ai_model} steps={payload.max_steps or settings.ai_max_steps}"
    started = perf_counter()
    status_code = 500
    ok = 0
    try:
        if not settings.ai_enabled:
            status_code = 503
            raise HTTPException(status_code=503, detail="AI is disabled. Set AI_ENABLED=true to enable.")
        if not settings.ai_base_url:
            status_code = 503
            raise HTTPException(status_code=503, detail="AI base URL is not configured.")

        service = AiChatService(
            client=OpenAICompatClient(
                base_url=settings.ai_base_url,
                api_key=settings.ai_api_key,
                timeout_seconds=settings.ai_request_timeout_seconds,
            ),
            model=settings.ai_model,
            temperature=settings.ai_temperature,
            max_steps=settings.ai_max_steps,
            sql_fallback_enabled=settings.ai_sql_fallback_enabled,
            max_output_tokens=settings.ai_max_output_tokens,
            max_history_messages=settings.ai_max_history_messages,
            max_message_chars=settings.ai_max_message_chars,
            max_tool_result_chars=settings.ai_tool_result_max_chars,
        )

        result = service.reply(
            db=db,
            messages=[m.model_dump() for m in payload.messages],
            max_steps=payload.max_steps,
        )
        status_code = 200
        ok = 1
    except ValueError as exc:
        status_code = 400
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        status_code = 502
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        latency_ms = int((perf_counter() - started) * 1000)
        try:
            db.execute(
                text(
                    """
                    INSERT INTO api_request_log (provider, endpoint, status_code, ok, latency_ms, cache_hit)
                    VALUES ('AI', :endpoint, :status_code, :ok, :latency_ms, 0)
                    """
                ),
                {
                    "endpoint": endpoint,
                    "status_code": status_code,
                    "ok": ok,
                    "latency_ms": latency_ms,
                },
            )
            db.commit()
        except Exception:
            db.rollback()

    return AiChatResponse(
        answer=result.answer,
        model=result.model,
        used_tools=result.used_tools,
        sources=_build_sources_from_trace(result.trace),
        sql_fallback_enabled=settings.ai_sql_fallback_enabled,
        steps=result.steps,
        trace=(result.trace if payload.include_trace else None),
    )
