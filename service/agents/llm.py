"""Shared LLM-call + JSON-parse helpers used by every LLM node.

Every node calls Gemini through the existing google-genai client
(ConfigService.get_genai_client) — we don't introduce a LangChain wrapper.
LangGraph's contribution is orchestration only.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Optional

from google.genai import types as genai_types

import config as ConfigService

logger = logging.getLogger(__name__)


# Global concurrency cap on Gemini calls. Vertex AI's per-project per-minute
# quota tolerates a small burst; with N variants × 5–6 agents per variant, an
# unconstrained pipeline produces 429s at higher N. The semaphore caps total
# in-flight calls regardless of which agent or variant is calling.
def _build_semaphore() -> asyncio.Semaphore:
    try:
        limit = int(os.environ.get("LLM_MAX_CONCURRENCY", "5"))
    except ValueError:
        limit = 5
    if limit < 1:
        limit = 1
    return asyncio.Semaphore(limit)


_SEMAPHORE: Optional[asyncio.Semaphore] = None


def _get_semaphore() -> asyncio.Semaphore:
    """Lazy-init so the semaphore binds to the running event loop, not to
    import-time. Avoids 'attached to a different loop' errors under uvicorn's
    auto-reload."""
    global _SEMAPHORE
    if _SEMAPHORE is None:
        _SEMAPHORE = _build_semaphore()
    return _SEMAPHORE


def _strip_json_fences(text: str) -> str:
    """Strip leading/trailing ```json ... ``` fences if present."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # First line is ```json (or ```), last line is ```. Drop both.
        if len(lines) >= 2:
            text = "\n".join(lines[1:-1])
    return text.strip()


def call_gemini_text_sync(
    *,
    prompt: str,
    max_output_tokens: int,
    temperature: float,
    label: str,
) -> str:
    """Single synchronous Gemini text call. Returns response.text or raises.

    `label` is a short tag included in log lines for grep-ability
    (e.g. "HOOK_SCOUT", "BUILDER:H1").
    """
    client = ConfigService.get_genai_client()
    resp = client.models.generate_content(
        model=ConfigService.CONFIG_TEXT_MODEL,
        contents=prompt,
        config=genai_types.GenerateContentConfig(
            max_output_tokens=max_output_tokens,
            temperature=temperature,
        ),
    )
    raw = getattr(resp, "text", None)
    if not raw:
        finish: Optional[str] = None
        try:
            finish = resp.candidates[0].finish_reason
        except Exception:
            pass
        raise ValueError(
            f"{label}: empty response from Gemini (finish_reason={finish}). "
            "Likely token budget exhausted before text emission."
        )
    return raw


async def call_gemini_text(
    *,
    prompt: str,
    max_output_tokens: int,
    temperature: float,
    label: str,
) -> str:
    """Async wrapper — runs the sync google-genai call in a thread so the
    LangGraph event loop stays free to fan out other nodes.

    Gated by a module-scope asyncio.Semaphore (LLM_MAX_CONCURRENCY env, default
    5) so the whole pipeline never exceeds N in-flight Gemini calls regardless
    of how many variants × agents are fanned out.
    """
    sem = _get_semaphore()
    if sem.locked() or (hasattr(sem, "_value") and sem._value == 0):  # noqa: SLF001
        logger.info(f"LLM_GATED label={label!r} waiting for semaphore slot")
    async with sem:
        return await asyncio.to_thread(
            call_gemini_text_sync,
            prompt=prompt,
            max_output_tokens=max_output_tokens,
            temperature=temperature,
            label=label,
        )


def parse_json_response(text: str, *, label: str) -> dict:
    """Strip code fences and parse the first JSON object from the response.

    Uses raw_decode so that extra data after the first object — e.g. Gemini
    occasionally emits a reasoning trailer or a second copy of the JSON — is
    tolerated. We take what's parseable and move on. Raises on actual
    structural failure (caller logs)."""
    cleaned = _strip_json_fences(text)
    decoder = json.JSONDecoder()
    try:
        obj, end = decoder.raw_decode(cleaned)
        if end < len(cleaned.rstrip()):
            tail_len = len(cleaned) - end
            logger.warning(
                f"{label}: ignoring {tail_len} bytes of trailing data "
                f"after first JSON object (model emitted extra)."
            )
        if not isinstance(obj, dict):
            raise ValueError(f"expected JSON object at top level, got {type(obj).__name__}")
        return obj
    except json.JSONDecodeError as e:
        logger.warning(
            f"{label}: JSON parse failed at pos {e.pos}: {e.msg}. "
            f"Raw head: {cleaned[:400]!r}"
        )
        raise
