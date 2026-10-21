"""The reasoning switch, mapped per catalogue switch kind (P1a-10, P1a-11).

A conversation's reasoning on or off (architecture §14.2) becomes request fields:

- ``thinking`` (DeepSeek and Qwen on Scaleway): off sends ``reasoning_effort: "none"``,
  which turns DeepSeek's thinking off on Scaleway (findings M2, checked live); on sends
  the catalogue entry's ``reasoning_effort_on``: ``"medium"`` for Qwen (none, low,
  medium, xhigh; owner decision Oct 19, 2026, findings C26), ``"high"`` for DeepSeek
  V4.1, which refuses ``"medium"`` (checked live, Oct 21, 2026).
- ``effort`` (GPT and Claude on OpenRouter): OpenRouter's unified ``reasoning`` object
  with effort ``reasoning_effort_on`` (``medium``) or ``none``, and ``exclude: true`` so
  the provider does not return reasoning text at all.
- ``none``: the model has no switch; only off is valid and nothing is sent.

Reasoning tokens count against the answer's output budget, so a call with reasoning on
gets ``app.llm.mistral.answer_max_tokens(True)``.

Whatever reasoning text a provider still returns is discarded by the stream reader and
never shown, stored or logged (``app.llm.scaleway.AnswerStream``).
"""

from __future__ import annotations

from typing import Any

from app.core.config import ReasoningSwitch


def reasoning_params(kind: ReasoningSwitch, on: bool, effort_on: str = "medium") -> dict[str, Any]:
    """Request body fields for ``on`` under switch ``kind``; ``effort_on`` when on."""
    if kind == "thinking":
        return {"reasoning_effort": effort_on if on else "none"}
    if kind == "effort":
        return {"reasoning": {"effort": effort_on if on else "none", "exclude": True}}
    if on:
        raise ValueError("this model has no reasoning switch")
    return {}


OPEN_TAG = "<think>"
CLOSE_TAG = "</think>"


class ThinkFilter:
    """Drops ``<think>…</think>`` blocks from streamed answer text (P1a-11).

    Some deployments put a reasoning model's thinking inline in ``content`` instead of
    a separate ``reasoning_content`` field. Tags may be split across deltas, so a
    possible tag prefix is held back until the next delta decides it. An unclosed block
    drops everything after its opening tag.
    """

    def __init__(self) -> None:
        self._pending = ""
        self._inside = False

    def feed(self, text: str) -> str:
        data = self._pending + text
        self._pending = ""
        out: list[str] = []
        while data:
            tag = CLOSE_TAG if self._inside else OPEN_TAG
            at = data.find(tag)
            if at >= 0:
                if not self._inside:
                    out.append(data[:at])
                data = data[at + len(tag) :]
                self._inside = not self._inside
                continue
            keep = _partial_suffix(data, tag)
            if not self._inside:
                out.append(data[: len(data) - keep])
            self._pending = data[len(data) - keep :]
            break
        return "".join(out)

    def flush(self) -> str:
        """End of stream: a held-back partial tag outside a block was answer text."""
        tail, self._pending = ("" if self._inside else self._pending), ""
        return tail


def _partial_suffix(text: str, tag: str) -> int:
    """Length of the longest suffix of ``text`` that is a proper prefix of ``tag``."""
    for size in range(min(len(text), len(tag) - 1), 0, -1):
        if tag.startswith(text[-size:]):
            return size
    return 0
