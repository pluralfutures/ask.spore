"""P1b-11: platform transactional mail. Templates, the sender over recorded (mocked)
provider transports, the configuration's allow-list, and the worker's send_mail jobs
against PostgreSQL: no address, subject or body in any log line, job row or audit row."""

from __future__ import annotations

import json
import logging
import re
import shutil
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import asyncpg
import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine

from app.content import worker
from app.core.config import (
    DEFAULT_CONFIG_DIR,
    ConfigError,
    MailConfig,
    MailgunConfig,
    load_settings,
)
from app.core.db import session_factory, tenant_session
from app.core.mail import MailError, MailSender, create_mail_sender
from app.core.mailtemplates import (
    OPERATOR_TEMPLATES,
    TEMPLATE_NAMES,
    check_template,
    first_name,
    load_template,
    render,
)
from app.mail.jobs import MailContext
from app.mail.queue import enqueue_operator_notice
from app.tenancy.models import INTERNAL_TENANT_ID
from tests.fakes import Recorder
from tests.test_auth import Auth, auth  # noqa: F401 - fixture
from tests.test_config import ENV, VALID_TOML, write_config
from tests.test_operator import (  # noqa: F401 - fixtures
    OPERATOR_EMAIL,
    Console,
    console,
    create,
    owner,
)
from tests.test_tenant_admin import admin_of

SETTINGS = load_settings(environ=ENV, config_dir=DEFAULT_CONFIG_DIR)
assert SETTINGS.models.mail is not None
MAIL: MailConfig = SETTINGS.models.mail
PROJECT = "11111111-2222-4333-8444-555555555555"
RECIPIENT = "invitee-7f3a@client.example"
SCALEWAY_URL = "https://api.scaleway.com/transactional-email/v1alpha1/regions/fr-par/emails"
UUID_PATTERN = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
URL_PATTERN = re.compile(r"https?://[^\s\"<>]+")
MAILGUN = MailgunConfig(base_url="https://api.eu.mailgun.net", domain="mg.example.org")


def ok() -> httpx.Response:
    return httpx.Response(200, json={"emails": [{"id": "synthetic", "status": "new"}]})


def sender(recorder: Recorder, config: MailConfig = MAIL, key: str = "tem-key") -> MailSender:
    return MailSender(
        config,
        api_key=SecretStr(key),
        project_id=PROJECT,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(recorder)),
    )


def mailgun_config(*, active: bool) -> MailConfig:
    return MAIL.model_copy(
        update={
            "provider": "mailgun" if active else "scaleway",
            "mailgun": MAILGUN,
        }
    )


# --- templates ------------------------------------------------------------------------------


@pytest.mark.parametrize("name", TEMPLATE_NAMES)
def test_rendering_carries_no_identifier_beyond_the_recipient_address(name: str) -> None:
    version = getattr(MAIL.templates, name)
    mail = render(
        load_template(DEFAULT_CONFIG_DIR, name, version),
        recipient_email=RECIPIENT,
        app_url=MAIL.app_url,
        recipient_display_name="Ada Synthetic-Surname",
    )
    for part in (mail.subject, mail.text, mail.html):
        assert "Synthetic-Surname" not in part  # never more of the name than the first word
        assert set(EMAIL_PATTERN.findall(part)) <= {RECIPIENT}
        assert UUID_PATTERN.search(part) is None
        assert all(url.startswith(MAIL.app_url) for url in URL_PATTERN.findall(part))
        assert "$" not in part  # every placeholder filled
    if name in OPERATOR_TEMPLATES:  # operators' notices name no tenant, not even the address
        assert RECIPIENT not in mail.text + mail.html
    else:
        assert RECIPIENT in mail.text and RECIPIENT in mail.html


@pytest.mark.parametrize("name", TEMPLATE_NAMES)
def test_subjects_read_sporebot(name: str) -> None:
    """P1b-17 (decision 1): the user-facing name; internal names stay ask.spore."""
    template = load_template(DEFAULT_CONFIG_DIR, name, getattr(MAIL.templates, name))
    mail = render(template, recipient_email=RECIPIENT, app_url=MAIL.app_url)
    assert "SporeBot" in mail.subject
    for part in (mail.subject, mail.text, mail.html):
        assert "ask.spore" not in part.lower() and "ask spore" not in part.lower()


def test_the_invitation_greets_the_recipient_by_first_name_and_nothing_else_does() -> None:
    """Decision 16: ``$first_name`` (the recipient's own) in the invitation only."""
    for name in TEMPLATE_NAMES:
        template = load_template(DEFAULT_CONFIG_DIR, name, getattr(MAIL.templates, name))
        mail = render(
            template,
            recipient_email=RECIPIENT,
            app_url=MAIL.app_url,
            recipient_display_name="Ada Synthetic",
        )
        if name == "invitation":
            assert "Hello Ada," in mail.text and "Hello Ada," in mail.html
        else:
            assert "Ada" not in mail.subject + mail.text + mail.html


@pytest.mark.parametrize(
    ("display_name", "expected"),
    [
        ("Ada Synthetic", "Ada"),
        ("  Ada\tSynthetic ", "Ada"),
        ("Ada", "Ada"),
        ("", "there"),
        (None, "there"),
        ("ada@client.example", "there"),
        ("A\x00da", "Ada"),
        ("x" * 200, "x" * 60),
    ],
)
def test_first_name_is_the_first_word_of_the_display_name(
    display_name: str | None, expected: str
) -> None:
    assert first_name(display_name) == expected


def test_the_first_name_is_escaped_in_html() -> None:
    template = load_template(DEFAULT_CONFIG_DIR, "invitation", MAIL.templates.invitation)
    mail = render(
        template,
        recipient_email=RECIPIENT,
        app_url=MAIL.app_url,
        recipient_display_name="<b>Ada</b> Synthetic",
    )
    assert "&lt;b&gt;Ada&lt;/b&gt;" in mail.html and "<b>Ada" not in mail.html


@pytest.mark.parametrize("name", sorted(set(TEMPLATE_NAMES) - {"invitation"}))
def test_another_template_using_first_name_refuses_startup(tmp_path: Path, name: str) -> None:
    """Operator notices stay tenant-free and name nobody; the consent notice too."""
    config = _config_copy(tmp_path)
    version = getattr(MAIL.templates, name)
    text = config / "mail" / name / f"{version}.txt"
    text.write_text(text.read_text(encoding="utf-8") + "\nHello $first_name.\n", encoding="utf-8")
    assert check_template(config, name, version)
    with pytest.raises(ConfigError) as excinfo:
        load_settings(environ=ENV, config_dir=config)
    assert any(p.startswith(f"mail.templates.{name}") for p in excinfo.value.problems)


def test_released_invitation_v1_is_unchanged_and_still_valid() -> None:
    v1 = load_template(DEFAULT_CONFIG_DIR, "invitation", "v1")
    assert "$first_name" not in v1.text + v1.html
    assert MAIL.templates.invitation == "v2"


def test_html_values_are_escaped(tmp_path: Path) -> None:
    template = load_template(DEFAULT_CONFIG_DIR, "invitation", MAIL.templates.invitation)
    mail = render(template, recipient_email="a<b>@client.example", app_url=MAIL.app_url)
    assert "a&lt;b&gt;@client.example" in mail.html and "a<b>" not in mail.html


def _config_copy(tmp_path: Path) -> Path:
    config = tmp_path / "config"
    shutil.copytree(DEFAULT_CONFIG_DIR, config)
    return config


@pytest.mark.parametrize(
    "placeholder", ["$tenant_name", "${user_id}", "$display_name", "$inviter_name", "$last_name"]
)
def test_a_template_with_another_placeholder_refuses_startup(
    tmp_path: Path, placeholder: str
) -> None:
    config = _config_copy(tmp_path)
    text = config / "mail" / "invitation" / f"{MAIL.templates.invitation}.txt"
    text.write_text(text.read_text(encoding="utf-8") + f"\nFor {placeholder}.\n", encoding="utf-8")
    assert check_template(config, "invitation", MAIL.templates.invitation)
    with pytest.raises(ConfigError) as excinfo:
        load_settings(environ=ENV, config_dir=config)
    assert any(p.startswith("mail.templates.invitation") for p in excinfo.value.problems)


def test_a_missing_template_version_refuses_startup(tmp_path: Path) -> None:
    config = _config_copy(tmp_path)
    (config / "mail" / "spend_cap_80" / f"{MAIL.templates.spend_cap_80}.html").unlink()
    with pytest.raises(ConfigError) as excinfo:
        load_settings(environ=ENV, config_dir=config)
    assert any(p.startswith("mail.templates.spend_cap_80") for p in excinfo.value.problems)


# --- configuration and the allow-list -----------------------------------------------------

MAIL_TOML = """
[mail]
provider = "{provider}"
from_address = "sporebot@example.org"
from_name = "SporeBot"
app_url = "https://app.example.org"
timeout_seconds = 10

[mail.scaleway]
base_url = "{scaleway}"
api_version = "v1alpha1"
region = "fr-par"

[mail.templates]
invitation = "v1"
spend_cap_80 = "v1"
spend_cap_100 = "v1"
tenant_name_flag = "v1"
consent_notice = "v1"
"""


def _mail_problems(
    tmp_path: Path,
    *,
    eu: tuple[str, ...] = ("api.mistral.ai", "ragflow", "api.scaleway.com", "api.eu.mailgun.net"),
    external: tuple[str, ...] = (),
    provider: str = "scaleway",
    scaleway: str = "https://api.scaleway.com",
    mailgun: str | None = None,
) -> list[str]:
    hosts = f"eu_hosts = {json.dumps(list(eu))}\nexternal_hosts = {json.dumps(list(external))}"
    text = VALID_TOML.replace('eu_hosts = ["api.mistral.ai", "ragflow"]', hosts)
    text += MAIL_TOML.format(provider=provider, scaleway=scaleway)
    if mailgun is not None:
        text += f'\n[mail.mailgun]\nbase_url = "{mailgun}"\napi_version = "v3"\n'
        text += 'domain = "mg.example.org"\n'
    config = write_config(tmp_path, text)
    shutil.copytree(DEFAULT_CONFIG_DIR / "mail", config / "mail")
    try:
        load_settings(environ=ENV, config_dir=config)
    except ConfigError as exc:
        return exc.problems
    return []


def test_repository_mail_config_is_valid() -> None:
    assert MAIL.provider == "scaleway"
    assert MAIL.scaleway is not None and MAIL.scaleway.region == "fr-par"
    assert MAIL.mailgun is None  # the backup is not configured
    eu = SETTINGS.models.allow_list.eu_hosts
    assert "api.scaleway.com" in eu and "api.eu.mailgun.net" in eu


def test_eu_mail_hosts_load(tmp_path: Path) -> None:
    assert _mail_problems(tmp_path, mailgun="https://api.eu.mailgun.net") == []


@pytest.mark.parametrize(
    ("kwargs", "setting"),
    [
        ({"eu": ("api.mistral.ai", "ragflow")}, "mail.scaleway.base_url"),  # unlisted
        ({"scaleway": "https://smtp.example.com"}, "mail.scaleway.base_url"),
        # Mailgun's US region, even when someone lists it as an external host.
        (
            {"mailgun": "https://api.mailgun.net", "external": ("api.mailgun.net",)},
            "mail.mailgun.base_url",
        ),
        ({"mailgun": "https://api.mailgun.net"}, "mail.mailgun.base_url"),
    ],
)
def test_allow_list_refuses_a_non_eu_mail_host(
    tmp_path: Path, kwargs: dict[str, Any], setting: str
) -> None:
    problems = _mail_problems(tmp_path, **kwargs)
    assert any(p.startswith(setting) and "eu_hosts" in p for p in problems), problems


def test_mail_hosts_need_https(tmp_path: Path) -> None:
    problems = _mail_problems(tmp_path, scaleway="http://api.scaleway.com")
    assert "mail.scaleway.base_url must use https" in problems


def test_the_backup_needs_its_section_to_be_active(tmp_path: Path) -> None:
    problems = _mail_problems(tmp_path, provider="mailgun")
    assert any("no [mail.mailgun]" in p for p in problems)


def test_no_sender_without_the_active_providers_key() -> None:
    assert create_mail_sender(SETTINGS) is None  # ENV has no SCALEWAY_TEM_API_KEY
    env = {**ENV, "SCALEWAY_TEM_API_KEY": "tem-key", "SCALEWAY_TEM_PROJECT_ID": PROJECT}
    built = create_mail_sender(load_settings(environ=env, config_dir=DEFAULT_CONFIG_DIR))
    assert built is not None and built.provider == "scaleway"
    # The Generative APIs project is the fallback for the sending project.
    env = {**ENV, "SCALEWAY_TEM_API_KEY": "tem-key", "SCALEWAY_PROJECT_ID": PROJECT}
    assert load_settings(environ=env).secrets.scaleway_tem_project_id == PROJECT
    # Mailgun's key does nothing while Scaleway is the provider.
    env = {**ENV, "MAILGUN_API_KEY": "mg-key"}
    assert create_mail_sender(load_settings(environ=env, config_dir=DEFAULT_CONFIG_DIR)) is None


# --- the sender ------------------------------------------------------------------------------


def _invitation() -> Any:
    return render(
        load_template(DEFAULT_CONFIG_DIR, "invitation", MAIL.templates.invitation),
        recipient_email=RECIPIENT,
        app_url=MAIL.app_url,
    )


async def test_scaleway_request() -> None:
    recorder = Recorder(ok())
    mail = _invitation()
    await sender(recorder).send(RECIPIENT, mail)
    (request,) = recorder.requests
    assert (request.method, str(request.url)) == ("POST", SCALEWAY_URL)
    assert request.headers["X-Auth-Token"] == "tem-key"
    body = json.loads(request.content)
    assert body == {
        "from": {"email": MAIL.from_address, "name": "SporeBot"},
        "to": [{"email": RECIPIENT}],
        "subject": mail.subject,
        "text": mail.text,
        "html": mail.html,
        "project_id": PROJECT,
    }


async def test_the_backup_is_used_only_when_configured() -> None:
    # Configured but not active: everything still goes to Scaleway.
    recorder = Recorder(ok())
    await sender(recorder, mailgun_config(active=False)).send(RECIPIENT, _invitation())
    assert [r.url.host for r in recorder.requests] == ["api.scaleway.com"]
    # Active: Mailgun's EU region only, with tracking off and the key as basic auth.
    recorder = Recorder(httpx.Response(200, json={"id": "<synthetic>", "message": "Queued"}))
    await sender(recorder, mailgun_config(active=True), key="mg-key").send(RECIPIENT, _invitation())
    (request,) = recorder.requests
    assert str(request.url) == "https://api.eu.mailgun.net/v3/mg.example.org/messages"
    assert request.headers["Authorization"] == "Basic YXBpOm1nLWtleQ=="  # api:mg-key
    form = dict(httpx.QueryParams(request.content.decode()))
    assert form["to"] == RECIPIENT and form["from"] == f"SporeBot <{MAIL.from_address}>"
    assert form["o:tracking"] == form["o:tracking-clicks"] == form["o:tracking-opens"] == "no"
    assert "X-Auth-Token" not in request.headers


@pytest.mark.parametrize(
    ("reply", "code", "retryable"),
    [
        (httpx.Response(503, json={"message": f"cannot deliver to {RECIPIENT}"}), "mail_503", True),
        (httpx.Response(429, text=f"slow down for {RECIPIENT}"), "mail_429", True),
        (httpx.Response(400, json={"message": f"bad recipient {RECIPIENT}"}), "mail_400", False),
        (httpx.Response(401, text="unauthorized"), "mail_401", False),
        (httpx.ReadTimeout("synthetic"), "mail_timeout", True),
        (httpx.ConnectError(f"synthetic {RECIPIENT}"), "mail_unreachable", True),
    ],
)
async def test_provider_failure_yields_an_error_code_only(
    reply: httpx.Response | Exception, code: str, retryable: bool
) -> None:
    with pytest.raises(MailError) as excinfo:
        await sender(Recorder(reply)).send(RECIPIENT, _invitation())
    assert (excinfo.value.error_code, excinfo.value.retryable) == (code, retryable)
    assert str(excinfo.value) == code and RECIPIENT not in repr(excinfo.value)
    error = excinfo.value  # no provider exception chained, which could carry the text
    assert error.__cause__ is None and (error.__context__ is None or error.__suppress_context__)


# --- send_mail jobs (worker, PostgreSQL) -----------------------------------------------------


@pytest.fixture
async def jobs(admin_conn: asyncpg.Connection) -> AsyncIterator[asyncpg.Connection]:
    await admin_conn.execute("DELETE FROM jobs")
    yield admin_conn
    await admin_conn.execute("DELETE FROM jobs")


def context(engine: AsyncEngine, mail_sender: MailSender | None) -> MailContext:
    return MailContext(
        factory=session_factory(engine),
        config=MAIL,
        config_dir=DEFAULT_CONFIG_DIR,
        sender=mail_sender,
    )


async def run_all(engine: AsyncEngine, ctx: MailContext) -> int:
    ran = 0
    registry = {"send_mail": worker.mail_handler(ctx)}
    while await worker.run_once(session_factory(engine), registry):
        ran += 1
    return ran


async def mail_jobs(conn: asyncpg.Connection) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        "SELECT payload, status, attempts, error_code FROM jobs WHERE type = 'send_mail' "
        "ORDER BY created_at"
    )
    return [{**dict(r), "payload": json.loads(r["payload"])} for r in rows]


def output(capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture) -> str:
    captured = capsys.readouterr()
    return captured.out + captured.err + "\n".join(r.getMessage() for r in caplog.records)


async def invite(console: Console) -> tuple[uuid.UUID, uuid.UUID, str]:  # noqa: F811
    op = await console.operator()
    tenant_id = uuid.UUID((await create(op))["id"])
    email = f"first-admin-{uuid.uuid4().hex[:6]}@client.example"
    response = await op.post(
        f"/api/v1/operator/tenants/{tenant_id}/admins",
        json={"email": email, "display_name": "Synthetic First Admin"},
    )
    assert response.status_code == 201, response.text
    return tenant_id, uuid.UUID(response.json()["user_id"]), email


async def test_the_first_admin_invite_sends_an_email_with_no_address_in_any_log(
    console: Console,  # noqa: F811
    engine: AsyncEngine,
    jobs: asyncpg.Connection,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Closes Phase 1a A15: the operator's invite sends an email at last."""
    caplog.set_level(logging.DEBUG)
    tenant_id, user_id, email = await invite(console)
    (job,) = await mail_jobs(jobs)
    # The payload names the template and the recipient by identifier only.
    assert job["payload"] == {
        "template": "invitation",
        "tenant_id": str(tenant_id),
        "user_id": str(user_id),
    }
    assert email not in json.dumps(job)

    recorder = Recorder(ok())
    capsys.readouterr()
    assert await run_all(engine, context(engine, sender(recorder))) == 1
    (request,) = recorder.requests
    body = json.loads(request.content)
    assert body["to"] == [{"email": email}]
    assert "SporeBot" in body["subject"] and email in body["text"]
    assert MAIL.app_url in body["text"]
    # The recipient's own first name (decision 16), not the rest of it, nor the inviter's.
    assert "Hello Synthetic," in body["text"] and "First Admin" not in request.content.decode()
    inviter = await console.auth.admin.fetchval(
        "SELECT display_name FROM users WHERE lower(email) = $1", OPERATOR_EMAIL
    )
    assert inviter and inviter not in request.content.decode()
    assert str(tenant_id) not in request.content.decode()

    (job,) = await mail_jobs(jobs)
    assert (job["status"], job["error_code"], job["attempts"]) == ("succeeded", None, 1)
    (event,) = await console.events("mail.sent", tenant_id)
    assert event["actor"] is None
    assert (event["template"], event["version"], event["provider"]) == (
        "invitation",
        MAIL.templates.invitation,
        "scaleway",
    )
    assert email not in json.dumps(event, default=str)

    # The log line: metadata only. No address, subject or body text, anywhere.
    logged = output(capsys, caplog)
    assert '"event":"mail.job"' in logged and '"template":"invitation"' in logged
    for text in (email, body["subject"], body["text"].splitlines()[2], "SporeBot", "Synthetic"):
        assert text not in logged


async def test_a_tenant_admins_invite_queues_an_invitation(
    auth: Auth,  # noqa: F811
    jobs: asyncpg.Connection,
) -> None:
    tenant, browser = await admin_of(auth)
    email = f"invitee-{uuid.uuid4().hex[:6]}@client.example"
    response = await browser.post(
        "/api/v1/admin/users", json={"email": email, "display_name": "Synthetic Invitee"}
    )
    assert response.status_code == 201, response.text
    (job,) = await mail_jobs(jobs)
    assert job["payload"] == {
        "template": "invitation",
        "tenant_id": str(tenant.id),
        "user_id": response.json()["id"],
    }


async def test_a_refused_invite_queues_nothing(
    console: Console,  # noqa: F811
    jobs: asyncpg.Connection,
) -> None:
    op = await console.operator()
    tenant_id = (await create(op))["id"]
    console.auth.idp.fail_mfa_sync = True  # Authentik refuses: the invite rolls back
    response = await op.post(
        f"/api/v1/operator/tenants/{tenant_id}/admins",
        json={"email": "nobody@client.example", "display_name": "N"},
    )
    assert response.status_code == 502
    assert await mail_jobs(jobs) == []


async def test_a_provider_failure_retries_then_fails_with_a_code_only(
    console: Console,  # noqa: F811
    engine: AsyncEngine,
    jobs: asyncpg.Connection,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    _, _, email = await invite(console)
    leak = {"message": f"mailbox {email} unavailable"}
    recorder = Recorder(httpx.Response(503, json=leak))
    capsys.readouterr()
    await run_all(engine, context(engine, sender(recorder)))
    (job,) = await mail_jobs(jobs)
    assert (job["status"], job["error_code"], job["attempts"]) == ("queued", "mail_503", 1)

    await jobs.execute("UPDATE jobs SET run_after = now(), attempts = max_attempts - 1")
    recorder.replies.append(httpx.Response(400, json=leak))
    await run_all(engine, context(engine, sender(recorder)))
    (job,) = await mail_jobs(jobs)
    assert (job["status"], job["error_code"]) == ("failed", "mail_400")
    logged = output(capsys, caplog)
    assert '"error_code":"mail_503"' in logged and '"error_code":"mail_400"' in logged
    assert email not in logged and "unavailable" not in logged


async def test_an_invitee_who_already_signed_in_gets_no_invitation(
    console: Console,  # noqa: F811
    engine: AsyncEngine,
    jobs: asyncpg.Connection,
) -> None:
    _, user_id, _ = await invite(console)
    await jobs.execute("UPDATE users SET status = 'active' WHERE id = $1", user_id)
    recorder = Recorder()  # any request would fail the test
    await run_all(engine, context(engine, sender(recorder)))
    assert recorder.requests == []
    (job,) = await mail_jobs(jobs)
    assert (job["status"], job["error_code"]) == ("failed", "recipient_gone")


async def test_without_a_key_nothing_is_sent(
    console: Console,  # noqa: F811
    engine: AsyncEngine,
    jobs: asyncpg.Connection,
) -> None:
    await invite(console)
    await run_all(engine, context(engine, None))
    (job,) = await mail_jobs(jobs)
    assert (job["status"], job["error_code"]) == ("failed", "mail_not_configured")


async def test_an_operator_notice_goes_to_every_operator(
    console: Console,  # noqa: F811
    engine: AsyncEngine,
    jobs: asyncpg.Connection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    await console.operator()
    operators = await jobs.fetch(
        "SELECT u.id, u.email FROM operators o JOIN users u ON u.id = o.user_id "
        "WHERE u.status <> 'deactivated'"
    )
    notice_id = uuid.uuid4()
    async with tenant_session(session_factory(engine), INTERNAL_TENANT_ID) as session:
        await enqueue_operator_notice(session, template="spend_cap_80", notice_id=notice_id)
    recorder = Recorder(*(ok() for _ in operators))
    capsys.readouterr()
    assert await run_all(engine, context(engine, sender(recorder))) == 1 + len(operators)
    sent_to = sorted(json.loads(r.content)["to"][0]["email"] for r in recorder.requests)
    assert sent_to == sorted(r["email"] for r in operators)
    first = json.loads(recorder.requests[0].content)
    assert "80" in first["subject"] and "SporeBot" in first["subject"]
    assert UUID_PATTERN.search(first["text"]) is None  # names no tenant or notice
    payloads = [j["payload"] for j in await mail_jobs(jobs)]
    assert payloads[0] == {"template": "spend_cap_80", "notice_id": str(notice_id)}
    assert {p.get("user_id") for p in payloads[1:]} == {str(r["id"]) for r in operators}
    assert all(r["email"] not in capsys.readouterr().out for r in operators)


async def test_enqueue_refuses_a_tenant_template_as_an_operator_notice(
    engine: AsyncEngine, jobs: asyncpg.Connection
) -> None:
    async with tenant_session(session_factory(engine), INTERNAL_TENANT_ID) as session:
        with pytest.raises(ValueError, match="not an operator template"):
            await enqueue_operator_notice(session, template="invitation", notice_id=uuid.uuid4())


async def test_the_database_refuses_a_mail_job_without_a_template_or_with_an_address(
    jobs: asyncpg.Connection,
) -> None:
    for payload in (
        '{"user_id": "x"}',
        '{"template": "invitation", "email": "someone@client.example"}',
        '{"template": "Subject: hello"}',
    ):
        with pytest.raises(asyncpg.CheckViolationError):
            await jobs.execute(
                "INSERT INTO jobs (type, payload) VALUES ('send_mail', $1::jsonb)", payload
            )
