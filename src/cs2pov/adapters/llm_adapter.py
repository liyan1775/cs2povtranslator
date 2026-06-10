from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


class LLMAdapterError(RuntimeError):
    pass


@dataclass(slots=True)
class OpenAICompatibleLLM:
    base_url: str
    api_key: str
    model: str
    timeout_seconds: int = 60

    def chat_json(self, system_prompt: str, user_prompt: str) -> Any:
        url = self.base_url.rstrip("/") + "/v1/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as resp:  # noqa: S310 - user configured URL
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise LLMAdapterError(f"LLM HTTP {exc.code}: {body[:500]}") from exc
        except Exception as exc:
            raise LLMAdapterError(f"LLM 请求失败：{exc}") from exc
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMAdapterError(f"LLM 未返回合法 JSON：{content[:500]}") from exc
