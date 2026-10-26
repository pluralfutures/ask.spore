"""P2A-L5: the sign-in email is short and holds nothing but the link.

The old template documented itself in a multi-line single-brace comment, which Django does
not treat as a comment: Authentik printed it into the email, with the double-brace url
variable expanded to the flow URL carrying the live ``?flow_token=`` in a query string.
These tests read the file (no Docker); CI's Authentik job renders it for real.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
TEMPLATE = REPO / "infra" / "authentik" / "templates" / "ask-spore-sign-in.html"


@pytest.fixture(scope="module")
def template() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def rendered_shape(template: str) -> str:
    """The template without its comment blocks: what Authentik would render, unevaluated."""
    return re.sub(r"\{% comment %\}.*?\{% endcomment %\}", "", template, flags=re.DOTALL)


def test_no_single_brace_comment(template: str) -> None:
    # Django's {# #} is single-line only; a multi-line one is printed into the email.
    assert "{#" not in template
    assert "#}" not in template


def test_the_only_variable_outside_comments_is_the_token(rendered_shape: str) -> None:
    assert re.findall(r"\{\{\s*([^}]*?)\s*\}\}", rendered_shape) == ["token"]
    assert "flow_token" not in rendered_shape
    assert "authentik-server" not in rendered_shape


def test_variables_stay_out_of_the_comment(template: str) -> None:
    comments = re.findall(r"\{% comment %\}(.*?)\{% endcomment %\}", template, flags=re.DOTALL)
    assert len(comments) == 1
    assert "{{" not in comments[0]


def test_one_link_to_the_fragment_landing_page(rendered_shape: str) -> None:
    hrefs = re.findall(r'href="([^"]*)"', rendered_shape)
    assert hrefs == ["https://askspore.myceliumgastronomy.com/auth/finish#token={{ token }}"]
    assert "?token" not in rendered_shape and "?flow" not in rendered_shape


def test_short_copy_without_identifiers(rendered_shape: str) -> None:
    text = re.sub(r"<[^>]+>|\{%[^%]*%\}|\{\{[^}]*\}\}", " ", rendered_shape)
    words = text.split()
    assert len(words) <= 40, len(words)
    assert "The link works once and expires in 15 minutes." in rendered_shape
    for forbidden in ("tenant", "workspace", "{{ user", "{{ email", "{{ name"):
        assert forbidden not in rendered_shape.lower()
