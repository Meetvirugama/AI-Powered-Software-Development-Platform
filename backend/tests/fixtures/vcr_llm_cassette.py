from __future__ import annotations

import copy
import difflib
import hashlib
import json
import os
import pathlib
import re
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Dict, List, Literal, Optional

CassetteMode = Literal["replay", "record", "auto"]

_SECRET_PATTERNS = [
    re.compile(r"(AIza[0-9A-Za-z\-_]{20,})"),
    re.compile(r"(gsk_[0-9A-Za-z]{20,})"),
    re.compile(r"(gh[pousr]_[0-9A-Za-z]{20,})"),
    re.compile(r"(sk-[0-9A-Za-z\-_]{20,})"),
    re.compile(r"(?i)(bearer\s+[0-9A-Za-z\-._~+/]+=*)"),
]

_SENSITIVE_KEY_SUBSTRINGS = (
    "api_key",
    "apikey",
    "authorization",
    "secret",
    "token",
    "password",
    "credential",
)


class VCRCacheMissError(KeyError):
    """Raised when a deterministic VCR cassette lookup misses in strict 'replay' mode."""


def redact_secrets_in_obj(value: Any) -> Any:
    """Recursively scrub API keys, bearer tokens, and secret fields before cassette persistence."""
    if isinstance(value, str):
        redacted = value
        for pattern in _SECRET_PATTERNS:
            redacted = pattern.sub("[REDACTED_SECRET]", redacted)
        return redacted
    if isinstance(value, list):
        return [redact_secrets_in_obj(item) for item in value]
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for k, v in value.items():
            key_lower = str(k).lower()
            if any(tok in key_lower for tok in _SENSITIVE_KEY_SUBSTRINGS):
                out[k] = "[REDACTED_SECRET]"
            else:
                out[k] = redact_secrets_in_obj(v)
        return out
    return value


def compute_canonical_llm_fingerprint(
    *,
    provider: str,
    model: str,
    messages: List[Dict[str, Any]],
    temperature: float = 0.0,
    response_schema: Optional[Dict[str, Any]] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Compute a canonical SHA-256 request fingerprint invariant to key ordering and secret rotation."""
    canonical_payload = {
        "provider": provider.strip().lower(),
        "model": model.strip(),
        "messages": redact_secrets_in_obj(messages),
        "temperature": round(float(temperature), 4),
        "response_schema": response_schema or None,
        "tools": tools or None,
    }
    encoded = json.dumps(canonical_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass
class VCRCassetteEntry:
    fingerprint: str
    provider: str
    model: str
    request: Dict[str, Any]
    response: Dict[str, Any]
    stream_chunks: List[str] = field(default_factory=list)


@dataclass
class VCRLLMCassette:
    """Deterministic VCR cassette store for unary and streaming LLM interactions."""

    cassette_path: pathlib.Path
    mode: CassetteMode = "replay"
    _entries: Dict[str, VCRCassetteEntry] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.cassette_path.exists():
            raw = json.loads(self.cassette_path.read_text(encoding="utf-8"))
            for item in raw.get("interactions", []):
                entry = VCRCassetteEntry(
                    fingerprint=item["fingerprint"],
                    provider=item["provider"],
                    model=item["model"],
                    request=item["request"],
                    response=item["response"],
                    stream_chunks=list(item.get("stream_chunks", [])),
                )
                self._entries[entry.fingerprint] = entry

    def save(self) -> None:
        """Persist cassette atomically via temp-file + POSIX os.replace."""
        self.cassette_path.parent.mkdir(parents=True, exist_ok=True)
        serialized = {
            "version": 1,
            "interactions": [
                {
                    "fingerprint": entry.fingerprint,
                    "provider": entry.provider,
                    "model": entry.model,
                    "request": redact_secrets_in_obj(entry.request),
                    "response": redact_secrets_in_obj(entry.response),
                    "stream_chunks": [redact_secrets_in_obj(c) for c in entry.stream_chunks],
                }
                for _, entry in sorted(self._entries.items(), key=lambda kv: kv[0])
            ],
        }
        payload_text = json.dumps(serialized, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        tmp_path = self.cassette_path.with_name(f".{self.cassette_path.name}.{os.getpid()}.tmp")
        tmp_path.write_text(payload_text, encoding="utf-8")
        os.replace(tmp_path, self.cassette_path)

    def _build_cache_miss_diagnostic(
        self,
        *,
        fingerprint: str,
        provider: str,
        model: str,
        messages: List[Dict[str, Any]],
    ) -> str:
        candidate_str = json.dumps(redact_secrets_in_obj(messages), indent=2, sort_keys=True)
        same_model = [
            e
            for e in self._entries.values()
            if e.provider.lower() == provider.lower() and e.model == model
        ]
        if not same_model:
            return (
                f"VCRLLMCassette cache miss in 'replay' mode for fingerprint={fingerprint} "
                f"(provider={provider}, model={model}). No entries recorded for this model."
            )
        closest = same_model[0]
        recorded_str = json.dumps(closest.request.get("messages", []), indent=2, sort_keys=True)
        diff_lines = list(
            difflib.unified_diff(
                recorded_str.splitlines(),
                candidate_str.splitlines(),
                fromfile=f"recorded:{closest.fingerprint[:12]}",
                tofile=f"actual:{fingerprint[:12]}",
                lineterm="",
            )
        )[:25]
        diff_preview = "\n".join(diff_lines)
        return (
            f"VCRLLMCassette cache miss for fingerprint={fingerprint} "
            f"(provider={provider}, model={model}). Prompt drift vs closest cassette entry:\n{diff_preview}"
        )

    async def execute_or_replay(
        self,
        *,
        provider: str,
        model: str,
        messages: List[Dict[str, Any]],
        temperature: float = 0.0,
        response_schema: Optional[Dict[str, Any]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        live_callable: Optional[Callable[[], Any]] = None,
    ) -> Dict[str, Any]:
        fingerprint = compute_canonical_llm_fingerprint(
            provider=provider,
            model=model,
            messages=messages,
            temperature=temperature,
            response_schema=response_schema,
            tools=tools,
        )
        if self.mode in ("replay", "auto") and fingerprint in self._entries:
            return copy.deepcopy(self._entries[fingerprint].response)

        if self.mode == "replay":
            raise VCRCacheMissError(
                self._build_cache_miss_diagnostic(
                    fingerprint=fingerprint,
                    provider=provider,
                    model=model,
                    messages=messages,
                )
            )

        if live_callable is None:
            raise RuntimeError("live_callable is required when recording a VCR LLM interaction")

        live_result = await live_callable()
        scrubbed_request = redact_secrets_in_obj(
            {
                "messages": messages,
                "temperature": round(float(temperature), 4),
                "response_schema": response_schema,
                "tools": tools,
            }
        )
        scrubbed_response = redact_secrets_in_obj(live_result)
        self._entries[fingerprint] = VCRCassetteEntry(
            fingerprint=fingerprint,
            provider=provider,
            model=model,
            request=scrubbed_request,
            response=scrubbed_response,
        )
        self.save()
        return copy.deepcopy(scrubbed_response)

    async def replay_stream(
        self,
        *,
        provider: str,
        model: str,
        messages: List[Dict[str, Any]],
        temperature: float = 0.0,
    ) -> AsyncIterator[str]:
        fingerprint = compute_canonical_llm_fingerprint(
            provider=provider,
            model=model,
            messages=messages,
            temperature=temperature,
        )
        if fingerprint not in self._entries:
            raise VCRCacheMissError(
                self._build_cache_miss_diagnostic(
                    fingerprint=fingerprint,
                    provider=provider,
                    model=model,
                    messages=messages,
                )
            )
        entry = self._entries[fingerprint]
        chunks = entry.stream_chunks or [str(entry.response.get("content", ""))]
        for chunk in chunks:
            yield str(chunk)
