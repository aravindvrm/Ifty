from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from sqlalchemy.orm import Session

from app.ai.openai_compat import OpenAICompatClient
from app.ai.tools import AiReadOnlyTools


@dataclass(slots=True)
class AiChatResult:
    answer: str
    model: str
    used_tools: list[str]
    trace: list[dict[str, Any]]
    steps: int


class AiChatService:
    def __init__(
        self,
        *,
        client: OpenAICompatClient,
        model: str,
        temperature: float,
        max_steps: int,
        sql_fallback_enabled: bool,
        max_output_tokens: int,
        max_history_messages: int,
        max_message_chars: int,
        max_tool_result_chars: int,
    ) -> None:
        self.client = client
        self.model = model
        self.temperature = temperature
        self.max_steps = max_steps
        self.sql_fallback_enabled = sql_fallback_enabled
        self.max_output_tokens = max(128, min(4096, int(max_output_tokens)))
        self.max_history_messages = max(2, min(30, int(max_history_messages)))
        self.max_message_chars = max(256, min(12000, int(max_message_chars)))
        self.max_tool_result_chars = max(256, min(12000, int(max_tool_result_chars)))

    def reply(
        self,
        *,
        db: Session,
        messages: list[dict[str, str]],
        max_steps: int | None = None,
    ) -> AiChatResult:
        clean_messages = []
        for m in messages:
            role = str(m.get("role") or "").strip().lower()
            content = str(m.get("content") or "").strip()
            if role not in {"system", "user", "assistant"}:
                continue
            if not content:
                continue
            clean_messages.append({"role": role, "content": content[: self.max_message_chars]})
        if clean_messages:
            clean_messages = clean_messages[-self.max_history_messages :]
        if not clean_messages:
            raise ValueError("At least one non-empty message is required")

        tools = AiReadOnlyTools(db=db)
        system_prompt = (
            "You are Ifty AI for institutional holdings data. "
            "Use tools for facts, be concise, and never invent numbers. "
            "If data is unavailable, state that clearly."
        )
        conversation: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        conversation.extend(clean_messages)

        used_tools: list[str] = []
        trace: list[dict[str, Any]] = []
        final_answer = ""
        limit = max(1, min(12, int(max_steps if max_steps is not None else self.max_steps)))
        executed_steps = 0

        for _ in range(limit):
            executed_steps += 1
            payload = {
                "model": self.model,
                "messages": conversation,
                "temperature": self.temperature,
                "max_tokens": self.max_output_tokens,
                "tools": tools.specs,
                "tool_choice": "auto",
            }
            response = self.client.chat_completions(payload)
            choice = (response.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            assistant_content = _content_to_text(message.get("content"))
            tool_calls = message.get("tool_calls") or []

            if tool_calls:
                conversation.append(
                    {
                        "role": "assistant",
                        "content": assistant_content,
                        "tool_calls": tool_calls,
                    }
                )

                for tool_call in tool_calls:
                    fn = ((tool_call or {}).get("function") or {})
                    tool_name = str(fn.get("name") or "").strip()
                    args_raw = fn.get("arguments")
                    args = _parse_tool_args(args_raw)
                    tool_result = tools.execute(tool_name=tool_name, args=args)
                    used_tools.append(tool_name)
                    trace.append(
                        {
                            "tool": tool_name,
                            "arguments": args,
                            "result": tool_result,
                        }
                    )
                    conversation.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.get("id"),
                            "name": tool_name,
                            "content": _compact_tool_result_for_model(
                                tool_name=tool_name,
                                tool_result=tool_result,
                                max_chars=self.max_tool_result_chars,
                            ),
                        }
                    )
                continue

            if assistant_content:
                final_answer = assistant_content
                break

        if not final_answer:
            final_answer = "I could not generate a complete answer with the current tool step limit."

        return AiChatResult(
            answer=final_answer,
            model=self.model,
            used_tools=used_tools,
            trace=trace,
            steps=executed_steps,
        )


def _parse_tool_args(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return {}
    return {}


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text_value = item.get("text")
                if isinstance(text_value, str) and text_value.strip():
                    parts.append(text_value.strip())
        return "\n".join(parts).strip()
    return ""


def _compact_tool_result_for_model(
    *,
    tool_name: str,
    tool_result: dict[str, Any],
    max_chars: int,
) -> str:
    compact: Any = tool_result
    if isinstance(tool_result, dict):
        compact = dict(tool_result)
        rows = compact.get("rows")
        if isinstance(rows, list) and len(rows) > 5:
            compact["rows"] = rows[:5]
            compact["rows_total"] = len(rows)
            compact["rows_truncated"] = len(rows) - 5

    raw = json.dumps(compact, default=str)
    if len(raw) <= max_chars:
        return raw

    trimmed = raw[: max(0, max_chars - 32)]
    return json.dumps(
        {
            "tool": tool_name,
            "truncated": True,
            "excerpt": trimmed,
        },
        default=str,
    )
