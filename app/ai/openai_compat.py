from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import requests


@dataclass(slots=True)
class OpenAICompatClient:
    base_url: str
    api_key: str
    timeout_seconds: float = 45.0
    _session: requests.Session = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")
        self._session = requests.Session()

    def chat_completions(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            response = self._session.post(
                url,
                json=payload,
                headers=headers,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(f"AI upstream request failed: {exc}") from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError("AI upstream returned non-JSON response") from exc

        if not isinstance(data, dict) or "choices" not in data:
            raise RuntimeError("AI upstream returned malformed chat completion payload")

        return data
