"""Platform mail templates (P1b-11): ``config/mail/<name>/<version>.txt`` and ``.html``.

Versioned files, like the prompts under ``config/prompts/``: changing an email means a
new version file and a change of ``[mail.templates]`` in ``config/models.toml``; a
released version is never edited. The text file's first line is ``Subject: …``, then
a blank line, then the plain-text body; the HTML file is the HTML body.

A template may use three placeholders and nothing else (``$product``, ``$app_url``,
``$recipient_email``), checked at startup (``app.core.config``) and again when a
template is loaded. So a rendered email can carry no identifier beyond the
recipient's own address: no tenant, user, workspace, notice or job ID, no tenant name
and no display name, by construction. Values are HTML-escaped in the HTML body.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Final, Literal

TemplateName = Literal[
    "invitation", "spend_cap_80", "spend_cap_100", "tenant_name_flag", "consent_notice"
]
TEMPLATE_NAMES: Final[tuple[TemplateName, ...]] = (
    "invitation",
    "spend_cap_80",
    "spend_cap_100",
    "tenant_name_flag",
    "consent_notice",
)
# Sent to every operator (fan-out at send time); the others go to one tenant user.
OPERATOR_TEMPLATES: Final[frozenset[str]] = frozenset(
    {"spend_cap_80", "spend_cap_100", "tenant_name_flag"}
)
PLACEHOLDERS: Final[frozenset[str]] = frozenset({"product", "app_url", "recipient_email"})
# The user-facing product name (owner decision 1 of Oct 22, 2026); internal names stay
# ask.spore.
PRODUCT_NAME: Final = "SporeBot"
SUBJECT_PREFIX: Final = "Subject: "
MAX_SUBJECT_CHARS: Final = 160
MAIL_DIR: Final = "mail"


class MailTemplateError(ValueError):
    """A template file is missing or malformed. The message names files, never values."""


@dataclass(frozen=True)
class MailTemplate:
    name: str
    version: str
    subject: str
    text: str
    html: str

    @property
    def ref(self) -> str:
        return f"{self.name}/{self.version}"


@dataclass(frozen=True)
class RenderedMail:
    subject: str
    text: str
    html: str


def _paths(config_dir: Path, name: str, version: str) -> tuple[Path, Path]:
    base = config_dir / MAIL_DIR / name
    return base / f"{version}.txt", base / f"{version}.html"


def _problems(parts: dict[str, str]) -> list[str]:
    problems: list[str] = []
    for part, text in parts.items():
        template = Template(text)
        if not template.is_valid():
            problems.append(f"{part} has a malformed placeholder ('$$' writes a dollar sign)")
            continue
        unknown = sorted(set(template.get_identifiers()) - PLACEHOLDERS)
        if unknown:
            problems.append(f"{part} uses placeholders other than {sorted(PLACEHOLDERS)}")
    return problems


def _parse(name: str, version: str, text_file: str, html_file: str) -> MailTemplate:
    first, _, rest = text_file.partition("\n")
    if not first.startswith(SUBJECT_PREFIX) or not first[len(SUBJECT_PREFIX) :].strip():
        raise MailTemplateError(f"{name}/{version}.txt must start with a 'Subject: ' line")
    subject = first[len(SUBJECT_PREFIX) :].strip()
    if len(subject) > MAX_SUBJECT_CHARS:
        raise MailTemplateError(f"{name}/{version}.txt subject is too long")
    body = rest.lstrip("\n")
    if not body.strip() or not html_file.strip():
        raise MailTemplateError(f"{name}/{version} has an empty body")
    problems = _problems({"subject": subject, "text": body, "html": html_file})
    if problems:
        raise MailTemplateError(f"{name}/{version}: " + "; ".join(problems))
    return MailTemplate(name, version, subject, body, html_file)


def load_template(config_dir: Path, name: str, version: str) -> MailTemplate:
    if name not in TEMPLATE_NAMES:
        raise MailTemplateError(f"not a mail template: {name}")
    text_path, html_path = _paths(config_dir, name, version)
    try:
        text_file = text_path.read_text(encoding="utf-8")
        html_file = html_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise MailTemplateError(f"{exc.filename} does not exist") from None
    return _parse(name, version, text_file, html_file)


def check_template(config_dir: Path, name: str, version: str) -> list[str]:
    """Startup check: the problems with one active template (empty when it is fine)."""
    try:
        load_template(config_dir, name, version)
    except MailTemplateError as exc:
        return [str(exc)]
    return []


def render(template: MailTemplate, *, recipient_email: str, app_url: str) -> RenderedMail:
    """Fill the three placeholders; the HTML body gets HTML-escaped values."""
    values = {"product": PRODUCT_NAME, "app_url": app_url, "recipient_email": recipient_email}
    escaped = {key: html.escape(value) for key, value in values.items()}
    return RenderedMail(
        subject=Template(template.subject).substitute(values),
        text=Template(template.text).substitute(values),
        html=Template(template.html).substitute(escaped),
    )
