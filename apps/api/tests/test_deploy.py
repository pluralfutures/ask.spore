"""P1c-10: the deploy script (infra/scripts/deploy.sh) and the Compose dependencies it
relies on. The dry run is exercised with stand-ins for ``docker`` and ``python3`` on the
PATH, so it needs neither a Docker daemon nor a registry."""

from __future__ import annotations

import json
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


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_the_script_is_read_whole_before_it_runs(tmp_path: Path) -> None:
    """Step 1 checks out another commit, which rewrites the running script on disk; bash
    reads a script as it goes, so the rest must already be parsed (P2B-06). Here the first
    git call rewrites the script; the script must still go on to its next git call."""
    copy = tmp_path / "infra" / "scripts" / "deploy.sh"
    copy.parent.mkdir(parents=True)
    shutil.copy(SCRIPT, copy)
    env, calls = _stubs(tmp_path, digests_ok=True)
    git = tmp_path / "bin" / "git"
    git.write_text(
        f'#!/bin/sh\necho "git $*" >> "{calls}"\n'
        '[ "$1" = status ] || exit 3\n'
        f"printf 'echo \"the new file ran\" >&2\\nexit 7\\n%s\\n' "
        f'"$(head -c 20000 /dev/zero | tr "\\\\0" "#")" > "{copy}"\n'
    )
    git.chmod(0o755)
    done = subprocess.run(  # noqa: S603 - a copy of the repository's own script
        [BASH, str(copy)], env=env, capture_output=True, text=True, check=False
    )
    assert "the new file ran" not in done.stderr
    assert "git fetch --quiet origin" in calls.read_text()
    assert done.returncode == 3


# Step 9 of the script, run as it is written against a stand-in for docker that plays a
# Compose project ("ask-spore-dev") with the containers below on the `ragflow` network.
STEP_9 = """
set -Eeuo pipefail
STEP=test
fail() { printf 'deploy: FAILED at %s: %s\\n' "$STEP" "$1" >&2; exit 1; }
step() { STEP="$1"; }
compose() { docker compose -f compose.yml "$@"; }
compose_all() { compose --profile auth --profile public "$@"; }
eval "$(sed -n '/^# The services step 9 starts/,/^step "10. checks"/p' "$SCRIPT" | sed '$d')"
"""

DOCKER_STUB = r"""#!/usr/bin/env python3
import json, os, sys
state = json.load(open(os.environ["STUB_STATE"]))
args = sys.argv[1:]
with open(os.environ["STUB_CALLS"], "a") as calls:
    calls.write(" ".join(args) + "\n")
joined = " ".join(args)
tier = ["ragflow-es", "ragflow-mysql", "ragflow", "ragflow-tei"] + (
    ["ragflow-ui"] if state["file_has_ui"] else []
)
services = {name: {"networks": {"ragflow": None}} for name in tier + ["api", "worker"]}
services["caddy"] = {"networks": {"app": None}}
networks = {
    "ragflow": {"name": "ask-spore-dev_ragflow", "internal": state["file_internal"]},
    "app": {"name": "ask-spore-dev_app"},
}
if args[0] == "compose":
    if "--dry-run" in args:
        if state["dry_run_says_recreate"]:
            print(" Network ask-spore-dev_ragflow Removing ")
    elif "config" in args and "--services" in args:
        print("\n".join(services))
    elif "config" in args and "json" in args:
        print(json.dumps({"name": "ask-spore-dev", "services": services, "networks": networks}))
    sys.exit(0)
if args[:2] == ["network", "inspect"]:
    name = args[-1]
    if "{{.Internal}}" in joined:
        print("true" if state["live_internal"].get(name) else "false")
    elif ".Containers" in joined:
        print(" ".join(state["on_ragflow"]) if name.endswith("_ragflow") else "")
    sys.exit(0)
if args[0] == "inspect":
    name = args[-1]
    if "project" in joined:
        print(state["projects"].get(name, "ask-spore-dev"))
    else:
        print(name.removeprefix("ask-spore-dev-").removeprefix("other-")[:-2])
    sys.exit(0)
sys.exit(0)
"""

ON_RAGFLOW = [
    "ask-spore-dev-api-1",
    "ask-spore-dev-worker-1",
    "ask-spore-dev-ragflow-1",
    "ask-spore-dev-ragflow-mysql-1",
]


def _run_step_9(
    tmp_path: Path, **state: object
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(DOCKER_STUB)
    docker.chmod(0o755)
    defaults: dict[str, object] = {
        "file_has_ui": True,
        "file_internal": True,
        "dry_run_says_recreate": False,
        "live_internal": {"ask-spore-dev_ragflow": True, "ask-spore-dev_app": False},
        "on_ragflow": ON_RAGFLOW,
        "projects": {},
    }
    (tmp_path / "state.json").write_text(json.dumps({**defaults, **state}))
    calls = tmp_path / "calls.txt"
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "STUB_STATE": str(tmp_path / "state.json"),
        "STUB_CALLS": str(calls),
        "SCRIPT": str(SCRIPT),
    }
    done = subprocess.run(  # noqa: S603 - fixed script, stand-in docker
        [BASH, "-c", STEP_9], env=env, capture_output=True, text=True, check=False
    )
    return done, calls.read_text().splitlines() if calls.exists() else []


def _index(lines: list[str], ending: str) -> int:
    return next(i for i, line in enumerate(lines) if line.endswith(ending))


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_a_changed_network_is_recreated_with_every_service_on_it(tmp_path: Path) -> None:
    """Findings 2B §3: `up -d ragflow` alone fails on the attached api and worker and leaves
    the stores without their names. api and worker come off first; the whole tier,
    ragflow-ui included, is recreated in one go; api and worker are recreated after."""
    done, lines = _run_step_9(
        tmp_path,
        dry_run_says_recreate=True,
        live_internal={"ask-spore-dev_ragflow": False, "ask-spore-dev_app": False},
    )
    assert done.returncode == 0, done.stderr
    off_api = _index(lines, "network disconnect ask-spore-dev_ragflow ask-spore-dev-api-1")
    off_worker = _index(lines, "network disconnect ask-spore-dev_ragflow ask-spore-dev-worker-1")
    tier = _index(
        lines, "up -d --force-recreate ragflow-es ragflow-mysql ragflow ragflow-tei ragflow-ui"
    )
    plain = _index(lines, "up -d ragflow caddy")
    ui = _index(lines, "--profile public up -d ragflow-ui")
    api = _index(lines, "up -d --force-recreate api worker")
    assert max(off_api, off_worker) < tier < plain < ui < api
    # The tier's own containers stay attached until Compose stops them; nothing is removed.
    assert not any(
        "disconnect ask-spore-dev_ragflow ask-spore-dev-ragflow" in line for line in lines
    )
    assert not any(line.startswith("rm ") for line in lines)


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_the_internal_flag_alone_triggers_the_recreation(tmp_path: Path) -> None:
    """Should Compose's dry-run wording change, a differing `internal` still counts."""
    done, lines = _run_step_9(
        tmp_path, live_internal={"ask-spore-dev_ragflow": False, "ask-spore-dev_app": False}
    )
    assert done.returncode == 0, done.stderr
    assert any("--force-recreate ragflow-es" in line for line in lines)


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_an_unchanged_network_is_left_alone(tmp_path: Path) -> None:
    done, lines = _run_step_9(tmp_path)
    assert done.returncode == 0, done.stderr
    assert not any("network disconnect" in line for line in lines)
    assert not any("--force-recreate ragflow" in line for line in lines)
    assert any(line.endswith("up -d --force-recreate api worker") for line in lines)


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_a_rollback_removes_the_proxy_the_older_file_does_not_have(tmp_path: Path) -> None:
    """Deploying a commit from before P2B-06: ragflow publishes the UI port itself again,
    so the old ragflow-ui container must go, and is not started."""
    done, lines = _run_step_9(
        tmp_path,
        file_has_ui=False,
        file_internal=False,
        dry_run_says_recreate=True,
        on_ragflow=[*ON_RAGFLOW, "ask-spore-dev-ragflow-ui-1"],
    )
    assert done.returncode == 0, done.stderr
    removed = _index(lines, "rm -f ask-spore-dev-ragflow-ui-1")
    tier = _index(lines, "up -d --force-recreate ragflow-es ragflow-mysql ragflow ragflow-tei")
    assert removed < tier
    assert not any(line.endswith("up -d ragflow-ui") for line in lines)
    assert "ragflow-ui removed (no longer in the compose file)" in done.stdout


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_a_container_from_another_project_stops_the_deploy(tmp_path: Path) -> None:
    """Fail closed: the script only takes its own project's containers off a network."""
    done, lines = _run_step_9(
        tmp_path,
        dry_run_says_recreate=True,
        on_ragflow=["other-thing-1", *ON_RAGFLOW],
        projects={"other-thing-1": "someone-else"},
    )
    assert done.returncode == 1
    assert "not in this Compose project" in done.stderr
    assert not any("--force-recreate" in line or "disconnect" in line for line in lines)
