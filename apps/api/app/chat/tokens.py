"""Token counts for the history and context caps (P1b-15 f).

Replaces the Phase 0 estimate of four characters per token. The counts come from the
DeepSeek V4 tokenizer (``deepseek-tokenizer``: the ``tokenizer.json`` of the V4 series
in the wheel, a pure-Python byte-level BPE, no network and no other dependency): the
platform's default and eval model is ``deepseek-v4.1-flash``. For the other catalogue
models (Qwen, and the external ones) it is a close stand-in, not their own tokenizer;
the caps are budgets for what we send, not provider limits. No tokenizer state, text
or count is logged here.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Protocol, cast


class _Tokenizer(Protocol):
    def encode(self, text: str, add_special_tokens: bool = True) -> list[int]: ...

    def decode(
        self,
        token_ids: list[int],
        skip_special_tokens: bool = False,
        clean_up_tokenization_spaces: bool = True,
    ) -> str: ...


@lru_cache(maxsize=1)
def _tokenizer() -> _Tokenizer:
    # Loaded on first use (about 0.25 s, the vocabulary from the installed wheel).
    from deepseek_tokenizer import ds_token  # type: ignore[import-untyped]

    return cast(_Tokenizer, ds_token)


def count_tokens(text: str) -> int:
    """How many tokens ``text`` is, without special tokens."""
    if not text:
        return 0
    return len(_tokenizer().encode(text, add_special_tokens=False))


def truncate_tokens(text: str, max_tokens: int) -> str:
    """``text`` cut to at most ``max_tokens`` tokens (whole tokens; a character split
    across the cut is dropped)."""
    if max_tokens <= 0:
        return ""
    ids = _tokenizer().encode(text, add_special_tokens=False)
    if len(ids) <= max_tokens:
        return text
    cut = _tokenizer().decode(ids[:max_tokens], clean_up_tokenization_spaces=False)
    return cut.rstrip("�")
