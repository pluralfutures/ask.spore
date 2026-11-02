"""P2B-03: a user renames one of their own conversations. Through the API, against
PostgreSQL: the title is the only field, other users' and expired conversations are not
found, the orchestrator's title never overwrites a user's, and no title reaches the logs."""

from __future__ import annotations

import uuid

import pytest

from tests.chat_fixtures import World
from tests.test_api import EDITOR, Harness, api

__all__ = ["api"]  # fixture

pytestmark = pytest.mark.usefixtures("database")


async def _title(world: World, conversation_id: str | uuid.UUID) -> str | None:
    value: str | None = await world.admin.fetchval(
        "SELECT title FROM conversations WHERE id = $1", uuid.UUID(str(conversation_id))
    )
    return value


async def test_rename_sets_a_trimmed_title_and_keeps_the_order(api: Harness) -> None:
    first = await api.conversation()
    second = await api.conversation()
    before = await api.world.admin.fetchval(
        "SELECT updated_at FROM conversations WHERE id = $1", uuid.UUID(first)
    )
    response = await api.request("PATCH", f"/conversations/{first}", json={"title": "  Q3 plan  "})
    assert response.status_code == 200
    assert response.json()["title"] == "Q3 plan"
    assert await _title(api.world, first) == "Q3 plan"
    after = await api.world.admin.fetchval(
        "SELECT updated_at FROM conversations WHERE id = $1", uuid.UUID(first)
    )
    assert after == before  # a rename does not reorder the list
    listed = await api.request("GET", "/conversations")
    ids = [c["id"] for c in listed.json()]
    assert ids.index(second) < ids.index(first)
    assert {c["id"]: c["title"] for c in listed.json()}[first] == "Q3 plan"


@pytest.mark.parametrize(
    "body",
    [
        {"title": ""},
        {"title": "   "},
        {"title": "x" * 121},
        {"title": "bell\x07"},
        {},
        {"title": "ok", "mode": "web_search"},
        {"title": "ok", "model": "other"},
    ],
)
async def test_rename_refuses_bad_bodies_and_other_fields(
    api: Harness, body: dict[str, str]
) -> None:
    conversation = await api.conversation()
    response = await api.request("PATCH", f"/conversations/{conversation}", json=body)
    assert response.status_code == 422
    assert await _title(api.world, conversation) is None


async def test_rename_accepts_the_longest_title(api: Harness) -> None:
    conversation = await api.conversation()
    response = await api.request(
        "PATCH", f"/conversations/{conversation}", json={"title": "x" * 120}
    )
    assert response.status_code == 200


async def test_another_users_conversation_cannot_be_renamed(api: Harness) -> None:
    mine = await api.conversation()
    theirs = await api.conversation(email=EDITOR)
    response = await api.request("PATCH", f"/conversations/{theirs}", json={"title": "Mine now"})
    assert response.status_code == 404
    assert await _title(api.world, theirs) is None
    # And the other way round: the editor cannot rename the analyst's.
    response = await api.request(
        "PATCH", f"/conversations/{mine}", json={"title": "Not yours"}, email=EDITOR
    )
    assert response.status_code == 404
    assert await _title(api.world, mine) is None


async def test_unknown_and_expired_conversations_are_not_found(api: Harness) -> None:
    missing = await api.request("PATCH", f"/conversations/{uuid.uuid4()}", json={"title": "x"})
    assert missing.status_code == 404
    expired = await api.world.new_conversation(expired=True)
    response = await api.request("PATCH", f"/conversations/{expired}", json={"title": "x"})
    assert response.status_code == 404
    assert await _title(api.world, expired) is None


async def test_the_first_answer_does_not_overwrite_a_renamed_title(api: Harness) -> None:
    conversation = await api.conversation()
    await api.request("PATCH", f"/conversations/{conversation}", json={"title": "My own title"})
    await api.ask(conversation, "What changed in 2025?", "Capacity grew.")
    assert await _title(api.world, conversation) == "My own title"


async def test_rename_leaves_no_title_in_logs_or_audit(
    api: Harness, capsys: pytest.CaptureFixture[str]
) -> None:
    conversation = await api.conversation()
    title = "Synthetic confidential title"
    capsys.readouterr()
    response = await api.request("PATCH", f"/conversations/{conversation}", json={"title": title})
    assert response.status_code == 200
    out = capsys.readouterr()
    assert title not in out.out + out.err
    audited = await api.world.admin.fetchval(
        "SELECT count(*) FROM audit_events WHERE metadata::text LIKE $1", f"%{title}%"
    )
    assert audited == 0
