from __future__ import annotations

import json
import logging
import re
from decimal import Decimal
from typing import Any

import httpx

from buildshift_orchestrator.config import Settings
from buildshift_orchestrator.router_config import role_model

log = logging.getLogger(__name__)


def parse_llm_json(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    # Recover JSON object if model wrapped prose
    if not raw.startswith("{"):
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            raw = raw[start : end + 1]
    if not raw or not raw.lstrip().startswith("{"):
        raise ValueError("LLM returned empty content (no JSON)")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("LLM response is not a JSON object")
    return data


def _looks_like_json(text: str) -> bool:
    s = (text or "").strip()
    if not s:
        return False
    if s.startswith("{") or s.startswith("["):
        return True
    return "{" in s and "}" in s


def _message_text(msg: dict[str, Any]) -> str:
    """Prefer real message content that looks like JSON; avoid reasoning prose."""
    content = (msg.get("content") or "").strip()
    if content and _looks_like_json(content):
        return content
    candidates: list[str] = []
    if content:
        candidates.append(content)
    for key in ("reasoning_content", "reasoning"):
        alt = msg.get(key)
        if isinstance(alt, str) and alt.strip():
            candidates.append(alt.strip())
    specific = msg.get("provider_specific_fields")
    if isinstance(specific, dict):
        for key in ("content", "reasoning", "reasoning_content"):
            alt = specific.get(key)
            if isinstance(alt, str) and alt.strip():
                candidates.append(alt.strip())
    for c in candidates:
        if _looks_like_json(c):
            return c
    return content or (candidates[0] if candidates else "")


def _usage_cost(usage: dict[str, Any]) -> Decimal:
    cost = Decimal(str(usage.get("cost") or 0))
    prompt_t = int(usage.get("prompt_tokens") or 0)
    completion_t = int(usage.get("completion_tokens") or 0)
    if cost <= 0 and (prompt_t or completion_t):
        cost = Decimal(prompt_t) * Decimal("0.000001") + Decimal(completion_t) * Decimal(
            "0.000005"
        )
    if cost <= 0:
        cost = Decimal("0.02")
    return cost


def _chat_once(
    client: httpx.Client,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
) -> dict[str, Any]:
    resp = client.post(url, headers=headers, json=body)
    if resp.status_code >= 400 and "response_format" in body:
        body = dict(body)
        body.pop("response_format", None)
        resp = client.post(url, headers=headers, json=body)
    if resp.status_code >= 400:
        raise RuntimeError(f"LLM HTTP {resp.status_code}: {resp.text[:1200]}")
    return resp.json()


def call_role_llm(
    settings: Settings,
    role: str,
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.3,
    timeout: float = 180.0,
    max_tokens: int = 8192,
) -> tuple[dict[str, Any], Decimal]:
    """Call LiteLLM chat completions for a router role; return (parsed JSON, cost)."""
    model = role_model(role)
    url = f"{settings.litellm_url.rstrip('/')}/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.litellm_master_key}",
        "Content-Type": "application/json",
    }
    sys_extra = (
        "CRITICAL: Reply with ONE JSON object only in the assistant message content. "
        "No markdown fences, no prose, no chain-of-thought. Start with '{' and end with '}'."
    )
    enriched = list(messages)
    if enriched and enriched[0].get("role") == "system":
        enriched[0] = {
            "role": "system",
            "content": f"{enriched[0].get('content', '')}\n\n{sys_extra}",
        }
    else:
        enriched.insert(0, {"role": "system", "content": sys_extra})

    body: dict[str, Any] = {
        "model": model,
        "messages": enriched,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }

    total_cost = Decimal("0")
    with httpx.Client(timeout=timeout) as client:
        data = _chat_once(client, url, headers, body)
        total_cost += _usage_cost(data.get("usage") or {})
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        content = _message_text(msg)
        try:
            return parse_llm_json(content), total_cost
        except (json.JSONDecodeError, ValueError) as first_exc:
            finish = choice.get("finish_reason")
            preview = (content or "")[:240] or "(empty)"
            log.warning(
                "%s LLM JSON parse failed model=%s finish=%s; retrying repair. preview=%r",
                role,
                model,
                finish,
                preview,
            )
            repair_messages = enriched + [
                {
                    "role": "assistant",
                    "content": (content or "")[:2000] or "(empty)",
                },
                {
                    "role": "user",
                    "content": (
                        "Your previous reply was not valid JSON "
                        f"(finish={finish}). Return ONLY the complete JSON object now, "
                        "starting with { and ending with }. No explanation."
                    ),
                },
            ]
            repair_body: dict[str, Any] = {
                "model": model,
                "messages": repair_messages,
                "temperature": 0.1,
                "max_tokens": max_tokens,
                "response_format": {"type": "json_object"},
            }
            data2 = _chat_once(client, url, headers, repair_body)
            total_cost += _usage_cost(data2.get("usage") or {})
            choice2 = (data2.get("choices") or [{}])[0]
            msg2 = choice2.get("message") or {}
            content2 = _message_text(msg2)
            try:
                return parse_llm_json(content2), total_cost
            except (json.JSONDecodeError, ValueError) as second_exc:
                preview2 = (content2 or "")[:400] or "(empty)"
                raise ValueError(
                    f"{role} returned unparseable JSON after repair "
                    f"(finish={choice2.get('finish_reason')}): {second_exc}; "
                    f"preview={preview2!r}"
                ) from first_exc
