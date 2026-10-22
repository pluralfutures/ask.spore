"""``run``: every item through the retrieval step, the full pipeline and the judge.

Environment (the same names as the API where they mean the same thing):

- ``MISTRAL_API_KEY``: the judge (any value with ``--mock-mistral``).
- ``RAGFLOW_API_KEY``, ``DATABASE_URL``: the retrieval step (package datasets,
  provenance and the source register are read, never written).
- ``EVAL_USER_EMAIL``: the user the API answers as, and either
  ``EVAL_SERVICE_PRIVATE_KEY`` (``[auth] mode = "oidc"``, P1b-15 a: the service
  identity's signing key) or ``PHASE0_BEARER_TOKEN`` (``mode = "phase0"``).
- ``EVAL_API_URL``, ``EVAL_RAGFLOW_URL``: defaults for ``--api-url`` / ``--ragflow-url``.
"""

from __future__ import annotations

import ipaddress
import os
import socket
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from app.chat.prompts import active_prompt
from app.core.config import Settings, load_settings
from app.core.db import create_engine, session_factory
from app.llm.factory import LLMClient, create_judge_client
from app.llm.mistral import MistralClient
from app.retrieval.ragflow import RagflowClient
from pydantic import SecretStr

from eval import mock, results
from eval.judge import Judge
from eval.metrics import aggregate, citation_precision, matches
from eval.pipeline import ApiPipeline, PipelineAnswer
from eval.records import CitationRecord, ItemResult, PipelineRecord, SourceRef
from eval.retrieval import DEFAULT_WORKSPACE, RetrievalStep, WorkspaceMissing
from eval.schema import EvalItem, load_set, set_sha256

REPO_ROOT = Path(__file__).resolve().parents[3]
RAGFLOW_VERSION_FILE = REPO_ROOT / "infra" / "ragflow" / "VERSION"
# The harness never touches the answer cache; REDIS_URL is required only by the shared
# configuration loader.
UNUSED_REDIS_URL = "redis://unused.invalid:6379/0"


class HarnessError(RuntimeError):
    """The run cannot start; nothing was written."""


@dataclass
class RunOptions:
    config: Path  # path to models.toml; its directory is the config directory
    set_path: Path
    api_url: str
    user_email: str
    results_root: Path
    ragflow_url: str | None = None
    mock_mistral: bool = False
    notes: list[str] = field(default_factory=list)
    limit: int | None = None
    exclude_labels: list[str] = field(default_factory=list)
    workspace: str = DEFAULT_WORKSPACE  # slug of an internal-tenant workspace (P1a-04)


def select_items(
    items: Sequence[EvalItem], exclude_labels: Sequence[str], limit: int | None
) -> tuple[list[EvalItem], list[str]]:
    """Items to run (without excluded labels, then the first ``limit``) and excluded ids."""
    excluded = [i.id for i in items if set(i.labels) & set(exclude_labels)]
    kept = [i for i in items if i.id not in set(excluded)]
    return (kept[:limit] if limit else kept), excluded


def load_harness_settings(config: Path, environ: Mapping[str, str]) -> Settings:
    env = dict(environ)
    env.setdefault("REDIS_URL", UNUSED_REDIS_URL)
    return load_settings(environ=env, config_dir=config.resolve().parent)


def _internal(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    addresses = {ipaddress.ip_address(info[4][0]) for info in infos}
    return bool(addresses) and all(a.is_private or a.is_loopback for a in addresses)


def with_ragflow_url(settings: Settings, url: str) -> Settings:
    """Point the retrieval step at RAGFlow from outside its Compose network.

    The host must be in the allow-list or resolve only to private or loopback
    addresses: RAGFlow has no public listener (CLAUDE.md).
    """
    host = urlsplit(url).hostname
    if host is None:
        raise HarnessError("--ragflow-url is not a valid URL")
    allowed = {h.lower() for h in settings.models.allow_list.eu_hosts}
    if host.lower() not in allowed and not _internal(host):
        raise HarnessError(
            f"--ragflow-url host '{host}' is neither allow-listed nor a private address; "
            "RAGFlow must not be reached over a public address"
        )
    ragflow = settings.models.ragflow.model_copy(update={"base_url": url})
    return replace(settings, models=settings.models.model_copy(update={"ragflow": ragflow}))


def git_state() -> tuple[str, bool]:
    def git(*args: str) -> str:
        return subprocess.run(  # noqa: S603 - fixed arguments, no shell
            ["git", *args],  # noqa: S607
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    try:
        return git("rev-parse", "--short=12", "HEAD"), bool(git("status", "--porcelain"))
    except (OSError, subprocess.CalledProcessError):
        return "nogit", True


def pipeline_record(item: EvalItem, answer: PipelineAnswer) -> PipelineRecord:
    expected = item.expected_source_ids
    refs = [SourceRef(c.source_id, c.canonical_url) for c in answer.citations]
    return PipelineRecord(
        outcome=answer.outcome,
        error_code=answer.error_code,
        answer=answer.answer,
        citations=[
            CitationRecord(
                marker=c.marker,
                chunk_id=c.chunk_id,
                source_id=c.source_id,
                canonical_url=c.canonical_url,
                title=c.title,
                page_or_slide=c.page_or_slide,
                expected=matches(expected, ref) if expected else None,
            )
            for c, ref in zip(answer.citations, refs, strict=True)
        ],
        citation_precision=citation_precision(refs, expected),
        cached=answer.cached,
        tokens_in=answer.tokens_in,
        tokens_out=answer.tokens_out,
        latency_ms=answer.latency_ms,
    )


def _progress(text: str) -> None:
    # Item IDs and outcomes only; never questions, answers or chunk text.
    sys.stderr.write(text + "\n")


def _config_meta(settings: Settings) -> dict[str, Any]:
    models = settings.models
    prompts = [active_prompt(settings, name).ref for name in ("corpus_only", "rewrite", "judge")]
    try:
        ragflow_version = RAGFLOW_VERSION_FILE.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        ragflow_version = "unknown"
    if models.llm.provider == "scaleway" and models.scaleway is not None:
        chat, rewrite = models.scaleway.chat_model, models.scaleway.rewrite_model
    else:
        chat, rewrite = models.mistral.chat_model, models.mistral.rewrite_model
    # P1b-15 c: the judge is pinned on its own ([eval]); the chat model without it.
    judge = models.eval.judge_model if models.eval is not None else chat
    judge_provider = models.eval.judge_provider if models.eval is not None else models.llm.provider
    return {
        "llm_provider": models.llm.provider,
        "chat_model": chat,
        "rewrite_model": rewrite,
        "judge_model": judge,
        "judge_provider": judge_provider,
        "vector_similarity_weight": models.chat.vector_similarity_weight,
        "prompts": prompts,
        "top_k": models.chat.top_k,
        "similarity_threshold": models.chat.similarity_threshold,
        "max_context_tokens": models.chat.max_context_tokens,
        "embedding_model": models.ragflow.embedding_model,
        "ragflow_version": ragflow_version,
    }


async def run(options: RunOptions, environ: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    report = load_set(options.set_path)
    if not report.ok:
        raise HarnessError("eval set is invalid:\n" + "\n".join(report.errors))
    items, excluded = select_items(report.items, options.exclude_labels, options.limit)

    settings = load_harness_settings(options.config, env)
    if options.ragflow_url:
        settings = with_ragflow_url(settings, options.ragflow_url)
    token = env.get("PHASE0_BEARER_TOKEN", "")
    git_sha, git_dirty = git_state()
    started_at = datetime.now(UTC)
    started = time.perf_counter()
    run_id = f"{started_at:%Y%m%dT%H%M%SZ}-{git_sha}"

    engine = create_engine(settings.secrets.database_url.get_secret_value())
    ragflow = RagflowClient.from_settings(settings)
    rewrite_system = active_prompt(settings, "rewrite").text
    llm: LLMClient
    if options.mock_mistral:  # dev only: Mistral-shaped lexical stand-in, whatever the provider
        llm = MistralClient(
            settings.models.mistral,
            settings.secrets.mistral_api_key or SecretStr("mock"),
            rewrite_system,
            http_client=httpx.AsyncClient(transport=mock.transport()),
        )
    else:
        llm = create_judge_client(settings)
    pipeline = ApiPipeline(
        options.api_url,
        token,
        options.user_email,
        service_key=env.get("EVAL_SERVICE_PRIVATE_KEY") or None,
    )
    warnings: list[str] = []
    item_results: list[ItemResult] = []
    try:
        try:
            await pipeline.check()
        except httpx.HTTPError as exc:
            raise HarnessError(
                f"API not reachable or not authorised: {type(exc).__name__}"
            ) from None
        step = RetrievalStep(settings, ragflow, session_factory(engine), options.workspace)
        try:
            await step.prepare()
        except WorkspaceMissing:
            raise HarnessError(
                f"the internal tenant has no workspace '{options.workspace}'"
            ) from None
        pipeline.workspace_id = step.workspace_id
        if not step.package.dataset_ids:
            raise HarnessError("the package has no datasets; run `ask-spore datasets sync`")
        judge_config = settings.models.eval
        judge = Judge(
            llm,
            active_prompt(settings, "judge").text,
            model=None
            if options.mock_mistral or judge_config is None
            else judge_config.judge_model,
            reasoning_effort="none"
            if judge_config is None
            else judge_config.judge_reasoning_effort,
        )
        for item in items:
            unknown = step.unknown_expected(item.expected_source_ids)
            if unknown:
                warnings.append(f"{item.id}: expected sources not in the register: {unknown}")
            retrieved = await step.run(item.question, item.expected_source_ids)
            answer = await pipeline.ask(item.question)
            record = pipeline_record(item, answer)
            verdicts = None
            if answer.outcome in ("answered", "unsupported"):
                verdicts = await judge.judge(answer.answer, answer.citations, retrieved.chunk_texts)
            item_results.append(
                ItemResult(
                    id=item.id,
                    type=item.type,
                    labels=list(item.labels),
                    expected_source_ids=list(item.expected_source_ids),
                    retrieval=retrieved.record,
                    pipeline=record,
                    judge=verdicts,
                )
            )
            _progress(
                f"{item.id}: {record.outcome}"
                f"{' (' + record.error_code + ')' if record.error_code else ''}"
                f" hit@10={retrieved.record.hit_at_10}"
            )
    finally:
        await pipeline.aclose()
        await llm.aclose()
        await ragflow.aclose()
        await engine.dispose()

    summary = aggregate(item_results)
    counts = summary["counts"]
    if counts["cached_answers"]:
        warnings.append(
            f"{counts['cached_answers']} answers came from the API's answer cache. They were "
            "produced with the same settings and prompts (P1a-05 cache key), but by an earlier "
            "model call; flush the cache to measure the model afresh."
        )
    if counts["excerpt_fallbacks"]:
        warnings.append(
            f"{counts['excerpt_fallbacks']} cited passages were judged from the truncated "
            "citation excerpt (cited chunk not in the retrieval step's results)."
        )
    if git_dirty:
        warnings.append("Run from a working tree with uncommitted changes.")
    meta = {
        "run_id": run_id,
        "started_at": started_at.isoformat(timespec="seconds"),
        "duration_s": round(time.perf_counter() - started, 1),
        "git_sha": git_sha,
        "git_dirty": git_dirty,
        "mocked": options.mock_mistral,
        "synthetic_set": all(i.synthetic for i in items),
        "notes": options.notes,
        "set": {
            "path": options.set_path.name,
            "sha256": set_sha256(options.set_path),
            "items_run": len(items),
            "items_in_set": len(report.items),
            "excluded_labels": options.exclude_labels,
            "excluded_items": excluded,
        },
        "config": _config_meta(settings),
        "corpus_version": step.package.corpus_version,
        "package_datasets": len(step.package.dataset_ids),
        "workspace": options.workspace,
        "warnings": warnings,
    }
    directory = options.results_root / run_id
    results.write(directory, results.build(meta, summary, item_results))
    return directory
