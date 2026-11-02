"""P2B-06: the RAGFlow tier has no route to the internet.

RAGFlow's Markdown parser fetches every image URL it finds (phase-2b-findings.md), and a
guard that blocks only private addresses lets public hosts through. So the network the tier
runs on is ``internal``: its containers reach each other and the API and workers that join it,
and nothing else. The one thing that needs a published port, the loopback web UI, goes
through a small proxy on a second network, which is not part of the tier.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[3]
RAGFLOW = REPO / "infra" / "ragflow" / "docker-compose.yml"
UI_PROXY = "ragflow-ui"
TIER_NETWORK = "ragflow"


def load() -> dict[str, Any]:
    compose: dict[str, Any] = yaml.safe_load(RAGFLOW.read_text(encoding="utf-8"))
    return compose


def networks_of(service: dict[str, Any]) -> list[str]:
    declared = service.get("networks") or []
    return list(declared)  # a list of names, or a mapping keyed by name


def test_the_tier_network_is_internal() -> None:
    assert load()["networks"][TIER_NETWORK].get("internal") is True


def test_no_tier_service_is_on_a_network_that_is_not_internal() -> None:
    compose = load()
    internal = {n for n, spec in compose["networks"].items() if (spec or {}).get("internal")}
    for name, service in compose["services"].items():
        if name == UI_PROXY:
            continue
        nets = networks_of(service)
        assert nets, f"{name} would join the default network, which has internet access"
        assert set(nets) <= internal, f"{name} is on a network with internet access"
        assert service.get("network_mode") is None, f"{name} sets network_mode"


def test_only_the_ui_proxy_publishes_a_port_and_it_is_on_loopback() -> None:
    compose = load()
    published = {n for n, s in compose["services"].items() if s.get("ports")}
    assert published == {UI_PROXY}
    assert all(str(p).startswith("127.0.0.1:") for p in compose["services"][UI_PROXY]["ports"])


def test_the_ui_proxy_bridges_the_tier_and_nothing_else_uses_its_network() -> None:
    compose = load()
    assert set(networks_of(compose["services"][UI_PROXY])) == {TIER_NETWORK, UI_PROXY}
    assert not (compose["networks"][UI_PROXY] or {}).get("internal")
    users = [n for n, s in compose["services"].items() if UI_PROXY in networks_of(s)]
    assert users == [UI_PROXY]


def test_the_app_services_that_call_ragflow_join_the_tier_network() -> None:
    dev = yaml.safe_load((REPO / "infra" / "compose.dev.yml").read_text(encoding="utf-8"))
    joined = [n for n, s in dev["services"].items() if TIER_NETWORK in networks_of(s)]
    assert {"api", "worker"} <= set(joined)
