"""The reasoning switch, mapped per catalogue switch kind (P1a-10, P1a-11).

A conversation's reasoning on or off (architecture §14.2) becomes request fields:

- ``thinking`` (DeepSeek and Qwen on Scaleway): off sends ``reasoning_effort: "none"``,
  which turns DeepSeek's thinking off on Scaleway (findings M2, checked live); on sends
  nothing, leaving the model's default, which is to think (findings M2, and C9 for Qwen).
- ``effort`` (GPT and Claude on OpenRouter): OpenRouter's unified ``reasoning`` object
  with effort ``medium`` or ``none``, and ``exclude: true`` so the provider does not
  return reasoning text at all.
- ``none``: the model has no switch; only off is valid and nothing is sent.

Whatever reasoning text a provider still returns is discarded by the stream reader and
never shown, stored or logged (``app.llm.scaleway.AnswerStream``).
"""

from __future__ import annotations

from typing import Any

from app.core.config import ReasoningSwitch


def reasoning_params(kind: ReasoningSwitch, on: bool) -> dict[str, Any]:
    """Request body fields for ``on`` under switch ``kind``."""
    if kind == "thinking":
        return {} if on else {"reasoning_effort": "none"}
    if kind == "effort":
        return {"reasoning": {"effort": "medium" if on else "none", "exclude": True}}
    if on:
        raise ValueError("this model has no reasoning switch")
    return {}
