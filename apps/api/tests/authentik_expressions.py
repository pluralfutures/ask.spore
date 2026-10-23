"""Run our Authentik expressions the way Authentik runs them (P1b-07, P1c-02).

``run_source_mapping`` executes the property mapping the API generates for a source
(``app.auth.authentik.mapping_expression``) as the body of a function of the variables
Authentik gives a source mapping. ``run_source_policy`` executes the blueprint's
``ask-spore-source-if-sso`` expression policy with the flow plan's context, as the flow
planner evaluates it, and returns whether it passes and the messages it added.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.auth.authentik import mapping_expression
from app.auth.provider import SourceSpec

REPO = Path(__file__).resolve().parents[3]
BLUEPRINT = REPO / "infra" / "authentik" / "blueprints" / "ask-spore.yaml"
SOURCE_POLICY = "ask-spore-source-if-sso"


def _function(name: str, params: str, body: str) -> Any:
    indented = "\n".join("    " + line for line in body.splitlines())
    namespace: dict[str, Any] = {}
    exec(f"def {name}({params}):\n{indented}", namespace)  # noqa: S102
    return namespace[name]


def run_source_mapping(spec: SourceSpec, **variables: Any) -> dict[str, Any]:
    handler = _function("handler", "info, properties, name_id, source", mapping_expression(spec))
    defaults = {"info": {}, "properties": {}, "name_id": None, "source": None}
    result: dict[str, Any] = handler(**{**defaults, **variables})
    return result


class _AnyTag(yaml.SafeLoader):
    """Reads the blueprint with its custom tags as plain values (only the policy is used)."""


_AnyTag.add_multi_constructor("!", lambda loader, suffix, node: None)


def source_policy_expression() -> str:
    blueprint = yaml.load(BLUEPRINT.read_text(encoding="utf-8"), Loader=_AnyTag)  # noqa: S506
    (policy,) = [
        e
        for e in blueprint["entries"]
        if e["model"] == "authentik_policies_expression.expressionpolicy"
        and e["identifiers"]["name"] == SOURCE_POLICY
    ]
    expression: str = policy["attrs"]["expression"]
    return expression


def run_source_policy(context: dict[str, Any], *, sso_flow: bool = True) -> tuple[bool, list[str]]:
    messages: list[str] = []
    policy = _function("policy", "context, ak_message, ak_is_sso_flow", source_policy_expression())
    passing = bool(policy(context, messages.append, sso_flow))
    return passing, messages
