"""Minimal OpenAI-compatible client (stdlib only) for Meta Model API and for
Muse Glimmer served from any OpenAI-compatible endpoint (vLLM, llama.cpp,
Ollama, Baseten, Modal, Fireworks)."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

META_BASE = "https://api.meta.ai/v1"


@dataclass
class LLMConfig:
    base_url: str
    api_key: str
    model: str
    reasoning_effort: str | None = None
    timeout: float = 180.0
    label: str = ""

    @staticmethod
    def for_agent(kind: str) -> "LLMConfig":
        """kind: 'spark' (Meta Model API) or 'glimmer' (open weights, any
        OpenAI-compatible server). Environment variables override defaults."""
        if kind == "spark":
            return LLMConfig(
                base_url=os.environ.get("META_API_BASE", META_BASE),
                api_key=os.environ.get("MODEL_API_KEY", ""),
                model=os.environ.get("WORLDLAB_SPARK_MODEL", "muse-spark-1.3"),
                reasoning_effort=os.environ.get("WORLDLAB_REASONING", "medium"),
                label="Muse Spark (Meta Model API)")
        if kind == "glimmer":
            return LLMConfig(
                base_url=os.environ.get("WORLDLAB_GLIMMER_BASE_URL", "http://localhost:8000/v1"),
                api_key=os.environ.get("WORLDLAB_GLIMMER_API_KEY", "none"),
                model=os.environ.get("WORLDLAB_GLIMMER_MODEL", "muse-glimmer"),
                reasoning_effort=None,
                label="Muse Glimmer (open weights)")
        raise ValueError(kind)

    @staticmethod
    def meta_vision() -> "LLMConfig":
        return LLMConfig(base_url=os.environ.get("META_API_BASE", META_BASE),
                         api_key=os.environ.get("MODEL_API_KEY", ""),
                         model=os.environ.get("WORLDLAB_SPARK_MODEL", "muse-spark-1.3"),
                         reasoning_effort="low", label="Meta vision")


class APIError(RuntimeError):
    def __init__(self, status: int, body: str):
        super().__init__(f"HTTP {status}: {body[:500]}")
        self.status = status
        self.body = body


class LLMClient:
    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg
        self.calls = 0
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0}

    def _post(self, path: str, body: dict, retries: int = 4) -> dict:
        url = self.cfg.base_url.rstrip("/") + path
        data = json.dumps(body).encode()
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.cfg.api_key}"}
        delay = 2.0
        for attempt in range(retries + 1):
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self.cfg.timeout) as r:
                    self.calls += 1
                    return json.loads(r.read().decode())
            except urllib.error.HTTPError as e:
                txt = e.read().decode(errors="replace")
                if e.code in (429, 500, 502, 503, 504) and attempt < retries:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise APIError(e.code, txt) from None
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt < retries:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise APIError(0, str(e)) from None
        raise APIError(0, "unreachable")

    def chat(self, messages: list[dict], tools: list[dict] | None = None,
             response_format: dict | None = None, reasoning_effort: str | None = None,
             max_tokens: int | None = None) -> dict:
        body: dict = {"model": self.cfg.model, "messages": messages}
        if tools:
            body["tools"] = tools
        if response_format:
            body["response_format"] = response_format
        eff = reasoning_effort or self.cfg.reasoning_effort
        if eff:
            body["reasoning_effort"] = eff
        if max_tokens:
            body["max_tokens"] = max_tokens
        r = self._post("/chat/completions", body)
        u = r.get("usage") or {}
        for k in self.usage:
            self.usage[k] += int(u.get(k, 0) or 0)
        return r["choices"][0]["message"]

    def responses(self, body: dict) -> dict:
        return self._post("/responses", body)


def responses_text(resp: dict) -> str:
    """Concatenate output_text parts from a (non-streamed) Responses API result."""
    if isinstance(resp.get("output_text"), str):
        return resp["output_text"]
    out = []
    for item in resp.get("output", []) or []:
        for part in item.get("content", []) or []:
            if part.get("type") in ("output_text", "text") and isinstance(part.get("text"), str):
                out.append(part["text"])
    return "".join(out)
