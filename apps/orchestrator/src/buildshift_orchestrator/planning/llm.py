from __future__ import annotations

import json
import re
from decimal import Decimal
from typing import Any

import httpx

from buildshift_orchestrator.config import Settings
from buildshift_orchestrator.router_config import role_model


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
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("LLM response is not a JSON object")
    return data


def call_role_llm(
    settings: Settings,
    role: str,
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.3,
    timeout: float = 180.0,
) -> tuple[dict[str, Any], Decimal]:
    """Call LiteLLM chat completions for a router role; return (parsed JSON, cost)."""
    model = role_model(role)
    url = f"{settings.litellm_url.rstrip('/')}/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.litellm_master_key}",
        "Content-Type": "application/json",
    }
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "response_format": {"type": "json_object"},
    }
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(url, headers=headers, json=body)
        if resp.status_code >= 400:
            body.pop("response_format", None)
            resp = client.post(url, headers=headers, json=body)
        if resp.status_code >= 400:
            raise RuntimeError(f"{role} LLM failed ({resp.status_code}): {resp.text[:1200]}")
        data = resp.json()

    content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    usage = data.get("usage") or {}
    cost = Decimal(str(usage.get("cost") or 0))
    prompt_t = int(usage.get("prompt_tokens") or 0)
    completion_t = int(usage.get("completion_tokens") or 0)
    if cost <= 0 and (prompt_t or completion_t):
        cost = Decimal(prompt_t) * Decimal("0.000001") + Decimal(completion_t) * Decimal(
            "0.000005"
        )
    if cost <= 0:
        cost = Decimal("0.02")
    return parse_llm_json(content), cost
