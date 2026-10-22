"""The use and privacy notice users accept (P1b-10): ``config/consent/<version>.md``.

Versioned files, like the prompts and mail templates: a new notice is a new version
file and a change of ``[consent] version`` in ``config/models.toml``; a released version
is never edited. The owner supplies the wording; the repository never invents legal
text. A file is::

    # <title>

    ## Summary
    <short plain-language summary, Markdown>

    ## Full notice
    <the full legal wording, Markdown>

Startup refuses an active version whose file is missing or lacks either section, and
warns while it still carries the ``[owner: final wording]`` placeholder marker.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

CONSENT_DIR: Final = "consent"
SUMMARY_HEADING: Final = "## Summary"
NOTICE_HEADING: Final = "## Full notice"
PLACEHOLDER_MARKER: Final = "[owner: final wording]"


class ConsentNoticeError(ValueError):
    """The notice file is missing or malformed. The message names the file only."""


@dataclass(frozen=True)
class ConsentNotice:
    version: str
    title: str
    summary: str
    text: str

    @property
    def is_placeholder(self) -> bool:
        return PLACEHOLDER_MARKER in self.summary or PLACEHOLDER_MARKER in self.text


def notice_path(config_dir: Path, version: str) -> Path:
    return config_dir / CONSENT_DIR / f"{version}.md"


def load_notice(config_dir: Path, version: str) -> ConsentNotice:
    path = notice_path(config_dir, version)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ConsentNoticeError(f"{path} does not exist") from None
    first, _, rest = raw.partition("\n")
    title = first.removeprefix("# ").strip()
    if not first.startswith("# ") or not title:
        raise ConsentNoticeError(f"{path.name} must start with a '# ' title line")
    head, found_summary, after = rest.partition(f"\n{SUMMARY_HEADING}\n")
    summary, found_notice, text = after.partition(f"\n{NOTICE_HEADING}\n")
    if not found_summary or not found_notice or head.strip():
        raise ConsentNoticeError(
            f"{path.name} must have '{SUMMARY_HEADING}' then '{NOTICE_HEADING}' sections"
        )
    if not summary.strip() or not text.strip():
        raise ConsentNoticeError(f"{path.name} has an empty section")
    return ConsentNotice(version, title, summary.strip(), text.strip())


def check_notice(config_dir: Path, version: str) -> list[str]:
    """Startup check: the problems with the active notice (empty when it is fine)."""
    try:
        load_notice(config_dir, version)
    except ConsentNoticeError as exc:
        return [str(exc)]
    return []
