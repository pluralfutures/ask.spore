"""Findings §12: no request text leaves the API through a database error.

A DBAPIError's message carries the statement's parameters unless the engine hides
them, and an exception that escapes the app is logged by uvicorn with its traceback.
These tests prove the negative case: the text is in neither stdout nor stderr (nor any
log record), while an allow-listed error line is. The database-backed cases (a NUL
character and a failing write against PostgreSQL) are in test_api.py.
"""

from __future__ import annotations

import asyncio
import json
import socket
from collections.abc import AsyncIterator

import httpx
import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from sqlalchemy.exc import DBAPIError

from app.api.schemas import (
    AskIn,
    FeedbackIn,
    UserInviteIn,
    WorkspaceCreateIn,
    WorkspacePromptIn,
)
from app.core.db import create_engine
from app.main import ErrorBoundary

SECRET = "synthetic-question-7f3a about capacity"


def _db_error() -> DBAPIError:
    """What SQLAlchemy raises without hide_parameters: the parameters in the message."""
    return DBAPIError(
        "INSERT INTO messages (content) VALUES ($1::VARCHAR)",
        (SECRET,),
        ValueError(f"invalid value {SECRET}"),
    )


def _failing_app(*, boundary: bool) -> FastAPI:
    app = FastAPI()

    @app.post("/messages/{message_id}/feedback")
    async def write(message_id: str) -> dict[str, str]:
        raise _db_error()

    @app.post("/stream")
    async def stream() -> StreamingResponse:
        async def body() -> AsyncIterator[bytes]:
            yield b"event: token\n\n"
            raise RuntimeError(SECRET)

        return StreamingResponse(body())

    if boundary:
        app.add_middleware(ErrorBoundary)
    return app


def test_engine_hides_parameters() -> None:
    engine = create_engine("postgresql+asyncpg://u:p@localhost:5432/db")
    assert engine.sync_engine.hide_parameters is True  # against PostgreSQL: test_api.py


async def test_failing_write_is_one_allow_listed_line_and_a_json_code(
    capfd: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    assert SECRET in str(_db_error())  # positive control: the message carries the text
    transport = httpx.ASGITransport(app=_failing_app(boundary=True))  # re-raises escapes
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        response = await http.post("/messages/abc/feedback", json={"comment": SECRET})
    assert response.status_code == 500
    assert response.json()["detail"] == "database_error"
    assert SECRET not in response.text
    out, err = capfd.readouterr()
    assert SECRET not in out and SECRET not in err and SECRET not in caplog.text
    (line,) = [json.loads(x) for x in out.splitlines() if '"api.error"' in x]
    assert line["error_code"] == "database_error"
    assert line["exception"] == "DBAPIError"
    assert line["route"] == "/messages/{message_id}/feedback"  # the template, not the path
    assert line["method"] == "POST"
    assert line["request_id"] == response.json()["request_id"]


async def test_exception_after_the_stream_started_ends_it_without_detail(
    capfd: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    transport = httpx.ASGITransport(app=_failing_app(boundary=True))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        response = await http.post("/stream")
    assert response.status_code == 200 and SECRET not in response.text
    out, err = capfd.readouterr()
    assert SECRET not in out and SECRET not in err and SECRET not in caplog.text
    assert '"error_code":"internal_error"' in out


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


async def _through_uvicorn(app: FastAPI) -> httpx.Response:
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_config=None, access_log=False)
    )
    task = asyncio.create_task(server.serve())
    try:
        while not server.started:  # noqa: ASYNC110 - uvicorn exposes no started event
            await asyncio.sleep(0.01)
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as http:
            return await http.post("/messages/abc/feedback", json={"comment": SECRET})
    finally:
        server.should_exit = True
        await task


@pytest.mark.parametrize("boundary", [True, False])
async def test_uvicorn_never_logs_the_text(
    boundary: bool, capfd: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    """Served by uvicorn: with the boundary the traceback never reaches uvicorn.error.
    Without it (the positive control) uvicorn logs the text, so the capture works."""
    response = await _through_uvicorn(_failing_app(boundary=boundary))
    assert response.status_code == 500
    out, err = capfd.readouterr()
    seen = out + err + caplog.text
    if boundary:
        assert SECRET not in seen and SECRET not in response.text
        assert '"event":"api.error"' in out
        assert "Exception in ASGI application" not in seen
    else:
        assert "Exception in ASGI application" in seen and SECRET in seen


@pytest.mark.parametrize("char", ["\x00", "\x01", "\x08", "\x0b", "\x0c", "\r", "\x1b", "\x1f"])
def test_control_characters_are_refused_in_free_text(char: str) -> None:
    text = f"capacity{char}growth"
    with pytest.raises(ValidationError):
        AskIn(question=text)
    with pytest.raises(ValidationError):
        FeedbackIn(rating="up", comment=text)
    with pytest.raises(ValidationError):
        WorkspacePromptIn(text=text)
    with pytest.raises(ValidationError):
        UserInviteIn(email="a@example.org", display_name=text)
    with pytest.raises(ValidationError):
        WorkspaceCreateIn(slug="ws", name="Workspace", tag_ids=[text], default_model="m")


def test_tab_and_newline_are_allowed() -> None:
    assert AskIn(question="line one\n\tline two").question == "line one\n\tline two"
    assert WorkspacePromptIn(text="Rule 1\nRule 2").text == "Rule 1\nRule 2"
