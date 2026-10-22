"""Platform transactional mail (P1b-11). The only module that sends email.

One ``httpx`` client, one provider at a time, chosen by ``[mail] provider`` in
``config/models.toml`` (Stack Decision, email row):

- ``scaleway``: Scaleway Transactional Email's HTTP API in fr-par (the primary), with
  ``SCALEWAY_TEM_API_KEY`` in the ``X-Auth-Token`` header and the sending project's ID
  in the body;
- ``mailgun``: Mailgun's EU region (the backup), only while the configuration names it,
  with ``MAILGUN_API_KEY``; click and open tracking off.

Hosts and API versions come from ``[mail]``, validated at startup against
``allow_list.eu_hosts``. Nothing here logs: the caller (the worker's ``send_mail``
job, ``app.mail.jobs``) logs the job ID, template and outcome, never the recipient's
address, the subject or the body. A failure is ``MailError`` with a short code and
whether another attempt may succeed; the provider's response body is never read into
it, so no address or text can travel in an error either.
"""

from __future__ import annotations

import base64
from typing import Final

import httpx
from pydantic import SecretStr

from app.core.config import MailConfig, Settings
from app.core.logging import silence_library_loggers
from app.core.mailtemplates import RenderedMail

# httpx logs each request's URL at INFO; Mailgun's URL names the sending domain only,
# but no library logger writes anything from this module.
silence_library_loggers("httpx", "httpcore")

RETRYABLE_STATUSES: Final = frozenset({408, 425, 429, 500, 502, 503, 504})


class MailError(Exception):
    """Sending failed. ``error_code`` is safe to log and store; ``retryable`` says whether
    the job should be tried again (timeouts, 429 and 5xx)."""

    def __init__(self, error_code: str, *, retryable: bool) -> None:
        super().__init__(error_code)
        self.error_code = error_code
        self.retryable = retryable


class MailNotConfigured(RuntimeError):
    """The active provider has no key (or project) in the environment."""


class MailSender:
    """Sends one rendered email to one recipient through the configured provider."""

    def __init__(
        self,
        config: MailConfig,
        *,
        api_key: SecretStr,
        project_id: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if config.provider == "scaleway" and (config.scaleway is None or project_id is None):
            raise MailNotConfigured("scaleway mail needs [mail.scaleway] and a project ID")
        if config.provider == "mailgun" and config.mailgun is None:
            raise MailNotConfigured("mailgun mail needs [mail.mailgun]")
        self._config = config
        self._key = api_key
        self._project_id = project_id
        self._owns_http = http_client is None
        self._http = http_client or httpx.AsyncClient(
            timeout=config.timeout_seconds, follow_redirects=False
        )

    @property
    def provider(self) -> str:
        return self._config.provider

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    def _request(self, to: str, mail: RenderedMail) -> httpx.Request:
        config = self._config
        sender = f"{config.from_name} <{config.from_address}>"
        if config.provider == "scaleway" and config.scaleway is not None:
            section = config.scaleway
            return self._http.build_request(
                "POST",
                f"{section.base_url}/transactional-email/{section.api_version}"
                f"/regions/{section.region}/emails",
                headers={"X-Auth-Token": self._key.get_secret_value()},
                json={
                    "from": {"email": config.from_address, "name": config.from_name},
                    "to": [{"email": to}],
                    "subject": mail.subject,
                    "text": mail.text,
                    "html": mail.html,
                    "project_id": self._project_id,
                },
            )
        if config.provider == "mailgun" and config.mailgun is not None:
            backup = config.mailgun
            credentials = base64.b64encode(f"api:{self._key.get_secret_value()}".encode())
            return self._http.build_request(
                "POST",
                f"{backup.base_url}/{backup.api_version}/{backup.domain}/messages",
                headers={"Authorization": "Basic " + credentials.decode("ascii")},
                data={
                    "from": sender,
                    "to": to,
                    "subject": mail.subject,
                    "text": mail.text,
                    "html": mail.html,
                    "o:tracking": "no",
                    "o:tracking-clicks": "no",
                    "o:tracking-opens": "no",
                },
            )
        raise MailNotConfigured(config.provider)  # __init__ refuses this already

    async def send(self, to: str, mail: RenderedMail) -> None:
        """Send, or raise ``MailError`` with a code (``mail_timeout``, ``mail_unreachable``,
        ``mail_<status>``)."""
        try:
            response = await self._http.send(self._request(to, mail))
        except httpx.TimeoutException:
            raise MailError("mail_timeout", retryable=True) from None
        except httpx.HTTPError:
            raise MailError("mail_unreachable", retryable=True) from None
        status = response.status_code
        await response.aclose()  # the body is never read: it can echo the address
        if 200 <= status < 300:
            return
        raise MailError(f"mail_{status}", retryable=status in RETRYABLE_STATUSES)


def create_mail_sender(settings: Settings) -> MailSender | None:
    """The configured provider's sender, or None without ``[mail]`` or its key (then every
    send_mail job fails with ``mail_not_configured``)."""
    config, secrets = settings.models.mail, settings.secrets
    if config is None:
        return None
    key = secrets.scaleway_tem_api_key if config.provider == "scaleway" else secrets.mailgun_api_key
    if key is None:
        return None
    try:
        return MailSender(config, api_key=key, project_id=secrets.scaleway_tem_project_id)
    except MailNotConfigured:
        return None
