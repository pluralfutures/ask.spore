"""P1c-10: the deploy script (infra/scripts/deploy.sh) and the Compose dependencies it
relies on. The dry run is exercised with stand-ins for ``docker`` and ``python3`` on the
PATH, so it needs neither a Docker daemon nor a registry."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "infra" / "scripts" / "deploy.sh"
RAGFLOW_COMPOSE = ROOT / "infra" / "ragflow" / "docker-compose.yml"


def test_ragflow_depends_on_its_embedding_service() -> None:
    """Phase 1b F3: started alone, RAGFlow could not embed; it now pulls in TEI."""
    services = yaml.safe_load(RAGFLOW_COMPOSE.read_text(encoding="utf-8"))["services"]
    assert "ragflow-tei" in services
    depends = services["ragflow"]["depends_on"]
    assert depends["ragflow-tei"]["condition"] in ("service_started", "service_healthy")


def test_the_script_does_what_the_release_did_by_hand() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    # Phase 1b F1: migrate has its own image; web-build is the production web app.
    assert "build migrate api worker web-build" in text
    assert "authentik-postgresql authentik-server authentik-worker" in text
    assert "run --rm migrate" in text
    # Phase 1b F3: RAGFlow starts with the application, and ragflow-tei is checked.
    assert "up -d ragflow caddy" in text and "up -d --force-recreate api worker" in text
    assert "check-credentials.py" in text and "compose port api 8000" in text
    assert "grep -qx ragflow-tei" in text
    # Liveness is the public /healthz; /api/v1/healthz needs a signed-in user (401 otherwise).
    assert '"$API_URL/healthz"' in text and "/api/v1/healthz" not in text
    # Phase 1b F2: the worker's mail warning stops the deploy.
    assert '"event":"worker.mail_not_configured"' in text
    assert 'export ASK_SPORE_DEPLOY_VERSION="${FULL_SHA:0:12}"' in text
    assert "datasets counts" in text
    # Metadata only: the resolved Compose file (with secrets) is never printed.
    assert "config --quiet" in text
    assert "config\n" not in text and "printenv" not in text and "set -x" not in text


BASH = shutil.which("bash") or "/bin/bash"


def run(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - the repository's own script, fixed arguments
        [BASH, str(SCRIPT), *args], env=env, capture_output=True, text=True, check=False
    )


def _stubs(tmp_path: Path, *, digests_ok: bool) -> tuple[dict[str, str], Path]:
    calls = tmp_path / "calls.txt"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(f'#!/bin/sh\necho "docker $*" >> "{calls}"\nexit 0\n')
    python = bin_dir / "python3"
    if digests_ok:
        body = 'echo "infra/compose.dev.yml: redis:7@sha256:aa (pinned)"\nexit 0\n'
    else:
        body = 'echo "infra/compose.dev.yml: caddy:2@sha256:bb (MOVED)"\nexit 1\n'
    python.write_text(f'#!/bin/sh\necho "python3 $*" >> "{calls}"\n{body}')
    for stub in (docker, python):
        stub.chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
    return env, calls


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_the_dry_run_checks_the_compose_config_and_the_digests_only(tmp_path: Path) -> None:
    env, calls = _stubs(tmp_path, digests_ok=True)
    done = run(env, "--dry-run", "--hub-mirror", "mirror.example")
    assert done.returncode == 0, done.stderr
    assert "dry run passed" in done.stdout
    lines = calls.read_text().splitlines()
    assert lines == [
        f"docker compose -f {ROOT}/infra/compose.dev.yml --profile auth --profile public "
        "config --quiet",
        f"python3 {ROOT}/infra/scripts/image-digests.py --check --hub-mirror mirror.example",
    ]


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_a_moved_digest_fails_the_dry_run_closed(tmp_path: Path) -> None:
    env, calls = _stubs(tmp_path, digests_ok=False)
    done = run(env, "--dry-run")
    assert done.returncode == 1
    assert "(MOVED)" in done.stderr and "nothing was deployed" in done.stderr
    assert "build" not in calls.read_text() and " up " not in calls.read_text()


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_the_script_refuses_a_malformed_commit(tmp_path: Path) -> None:
    env, calls = _stubs(tmp_path, digests_ok=True)
    done = run(env, "--commit", "main; rm -rf /")
    assert done.returncode == 1
    assert "commit hash" in done.stderr
    assert not calls.exists()
