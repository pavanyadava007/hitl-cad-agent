"""Minimal local LLM client (Ollama HTTP API) with timing and an on-disk cache.

Only localhost endpoints are allowed: the point of the study is that nothing
leaves the machine. Responses are cached by a hash of the full request, which is
sound at temperature 0 and lets an interrupted evaluation resume; cached entries
keep the latency measured when they were first produced.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import requests

DEFAULT_HOSTS = {
    "llama3.1:8b": "http://127.0.0.1:11437",
}
DEFAULT_HOST = "http://127.0.0.1:11436"


@dataclass
class LLMReply:
    text: str
    latency_s: float
    prompt_tokens: int
    output_tokens: int
    eval_s: float
    cached: bool = False

    @property
    def tokens_per_s(self) -> float:
        return self.output_tokens / self.eval_s if self.eval_s > 0 else 0.0


class LocalLLM:
    def __init__(self, model: str, host: str | None = None, seed: int = 0, temperature: float = 0.0,
                 num_ctx: int = 8192, cache_dir: str | Path | None = ".cache/llm", timeout_s: float = 600):
        self.model = model
        self.host = host or os.environ.get("HCA_OLLAMA_HOST") or DEFAULT_HOSTS.get(model, DEFAULT_HOST)
        if urlparse(self.host).hostname not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError(f"refusing non-local LLM endpoint {self.host!r} (local-only by design)")
        self.options = {"temperature": temperature, "seed": seed, "num_ctx": num_ctx, "num_predict": 2048}
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.timeout_s = timeout_s

    def _key(self, messages, fmt) -> str:
        blob = json.dumps({"m": self.model, "o": self.options, "msgs": messages, "f": fmt}, sort_keys=True)
        return hashlib.sha256(blob.encode()).hexdigest()

    def chat(self, messages: list[dict], json_mode: bool = False) -> LLMReply:
        fmt = "json" if json_mode else None
        key = self._key(messages, fmt)
        if self.cache_dir:
            path = self.cache_dir / key[:2] / f"{key}.json"
            if path.exists():
                d = json.loads(path.read_text())
                return LLMReply(**{**d, "cached": True})
        body = {"model": self.model, "messages": messages, "stream": False, "options": self.options, "keep_alive": "30m"}
        if fmt:
            body["format"] = fmt
        t0 = time.perf_counter()
        r = requests.post(f"{self.host}/api/chat", json=body, timeout=self.timeout_s)
        dt = time.perf_counter() - t0
        r.raise_for_status()
        d = r.json()
        rep = LLMReply(
            text=d["message"]["content"],
            latency_s=dt,
            prompt_tokens=int(d.get("prompt_eval_count", 0)),
            output_tokens=int(d.get("eval_count", 0)),
            eval_s=float(d.get("eval_duration", 0)) / 1e9,
        )
        if self.cache_dir:
            path.parent.mkdir(parents=True, exist_ok=True)
            out = {k: v for k, v in rep.__dict__.items() if k != "cached"}
            path.write_text(json.dumps(out))
        return rep

    def warmup(self) -> None:
        """Load the model into VRAM so the first measured call is not a cold start."""
        body = {"model": self.model, "messages": [{"role": "user", "content": "ok"}], "stream": False,
                "options": {**self.options, "num_predict": 1}, "keep_alive": "30m"}
        requests.post(f"{self.host}/api/chat", json=body, timeout=self.timeout_s).raise_for_status()

    def unload(self) -> None:
        try:
            requests.post(f"{self.host}/api/generate", json={"model": self.model, "keep_alive": 0}, timeout=60)
        except requests.RequestException:
            pass
