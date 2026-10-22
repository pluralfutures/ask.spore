"""P0-11: corpus manifest validation and ``ask-spore ingest-manifest``."""

from __future__ import annotations

import csv
import io
import json
import shutil
from datetime import date
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from app import cli
from app.content.ingest import IngestResult, load_path
from app.content.manifest import (
    COLUMNS,
    ManifestError,
    ManifestRow,
    RowOutcome,
    load_manifest,
    run_manifest,
    write_summary,
)
from app.content.tags import load_tags
from app.core.config import DEFAULT_CONFIG_DIR, load_settings
from tests.test_datasets_sync import ENV
from tests.test_ingest import DOCX, PDF, PPTX, Env, Ingest, env

__all__ = ["env"]  # the DB-backed fixture, reused for the idempotency test

TAGS = load_tags(DEFAULT_CONFIG_DIR)
HEADER = ",".join(COLUMNS)
PDF_ROW = (
    "reports/tidewater.pdf,,pdf,sample-reports,Tidewater Outlook,Fictional Institute,"
    "2026-03-01,https://example.org/tidewater,public,en,,"
)
DOCX_ROW = (
    "analysis/brightwater.docx,,docx,sample-analysis;sample-reports,Brightwater note,"
    "Us,2025,,own-work,en,,two tags"
)
PPTX_ROW = "analysis/kestrel.pptx,,pptx,sample-analysis,Kestrel briefing,Us,2025-01-02,,own-work,,,"
SITE_ROW = (
    ",https://site.example/,site,sample-web,Site,Site Owner,2025-10-01,"
    "https://site.example/,publisher-terms,en,7,"
)


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    (tmp_path / "reports").mkdir()
    (tmp_path / "analysis").mkdir()
    shutil.copy(PDF, tmp_path / "reports" / "tidewater.pdf")
    shutil.copy(DOCX, tmp_path / "analysis" / "brightwater.docx")
    shutil.copy(PPTX, tmp_path / "analysis" / "kestrel.pptx")
    return tmp_path


def write(corpus: Path, *rows: str, header: str = HEADER) -> Path:
    manifest = corpus / "manifest.csv"
    manifest.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")
    return manifest


def problems(manifest: Path) -> tuple[str, ...]:
    with pytest.raises(ManifestError) as caught:
        load_manifest(manifest, TAGS)
    return caught.value.problems


def test_valid_rows_are_parsed(corpus: Path) -> None:
    rows = load_manifest(write(corpus, PDF_ROW, DOCX_ROW, PPTX_ROW, "", SITE_ROW), TAGS)

    pdf, docx, pptx, site = rows
    assert [r.line for r in rows] == [2, 3, 4, 6]
    assert pdf.type == "pdf"
    assert pdf.path == corpus / "reports" / "tidewater.pdf"
    assert pdf.metadata.tags == ("sample-reports",)
    assert pdf.metadata.published_on == date(2026, 3, 1)
    assert pdf.metadata.canonical_url == "https://example.org/tidewater"
    assert pdf.metadata.licence_basis == "public"
    assert docx.metadata.tags == ("sample-analysis", "sample-reports")
    assert docx.metadata.published_on == date(2025, 1, 1)  # year only
    assert docx.metadata.canonical_url is None  # own work needs none
    assert pptx.metadata.published_on == date(2025, 1, 2)
    assert (site.type, site.url, site.path, site.max_pages) == (
        "site",
        "https://site.example/",
        None,
        7,
    )


def test_byte_order_mark_and_quoted_commas(corpus: Path) -> None:
    manifest = corpus / "manifest.csv"
    row = PDF_ROW.replace("Tidewater Outlook", '"Tidewater, Outlook"')
    manifest.write_text(HEADER + "\n" + row + "\n", encoding="utf-8-sig")
    [parsed] = load_manifest(manifest, TAGS)
    assert parsed.metadata.title == "Tidewater, Outlook"


def test_every_problem_is_reported_at_once(corpus: Path) -> None:
    found = problems(
        write(
            corpus,
            PDF_ROW.replace("sample-reports", "reports"),  # unknown tag
            PDF_ROW.replace("reports/tidewater.pdf", "reports/missing.pdf"),
            PDF_ROW.replace(",pdf,", ",docx,"),  # extension does not match
            PDF_ROW.replace("2026-03-01", "1 March 2026"),
            PDF_ROW.replace(",public,", ",cc-by,"),
            PDF_ROW.replace("https://example.org/tidewater", ""),  # third party, no link
            PDF_ROW.replace("reports/tidewater.pdf", "../outside.pdf"),
            PDF_ROW.replace(",en,", ",English,"),
        )
    )
    assert [p.split(":")[0] for p in found] == [
        "line 2, tags",
        "line 3, path",
        "line 4, path",
        "line 5, published_on",
        "line 6, licence_basis",
        "line 7, canonical_url",
        "line 8, path",
        "line 9, language",
    ]


def test_site_and_file_columns_are_not_mixed(corpus: Path) -> None:
    found = problems(
        write(
            corpus,
            SITE_ROW.replace(",https://site.example/,site", "reports/tidewater.pdf,,site"),
            SITE_ROW.replace(",7,", ",lots,"),
            PDF_ROW.replace(",en,,", ",en,5,"),
            PDF_ROW.replace("tidewater.pdf,,", "tidewater.pdf,https://x.example/,"),
            SITE_ROW.replace(",site,", ",website,"),
        )
    )
    assert {p.split(":")[0] for p in found} == {
        "line 2, path",
        "line 2, url",
        "line 3, max_pages",
        "line 4, max_pages",
        "line 5, url",
        "line 6, type",
    }


def test_duplicate_file_names_and_sites_are_rejected(corpus: Path) -> None:
    (corpus / "other").mkdir()
    shutil.copy(PDF, corpus / "other" / "tidewater.pdf")
    found = problems(
        write(
            corpus,
            PDF_ROW,
            PDF_ROW.replace("reports/", "other/"),
            SITE_ROW,
            SITE_ROW.replace("https://site.example/,site", "https://site.example,site"),
        )
    )
    assert found == (
        "line 3, path: file name already used on line 2",
        "line 5, url: site already listed on line 4",
    )


def test_wrong_header_is_rejected(corpus: Path) -> None:
    found = problems(write(corpus, PDF_ROW, header=HEADER.replace("licence_basis", "licence")))
    assert found == (
        "line 1: header is missing required columns: licence_basis",
        "line 1: unknown columns: 'licence' (the only optional column is downloadable)",
    )


def reorder(row: str, header: list[str], order: list[str]) -> str:
    """``row``, written for ``header``, with its fields in the column order ``order``."""
    [fields] = csv.reader([row])
    by_name = dict(zip(header, fields, strict=True))
    out = io.StringIO()
    csv.writer(out, lineterminator="").writerow([by_name[name] for name in order])
    return out.getvalue()


def test_columns_are_matched_by_name_in_any_order(corpus: Path) -> None:
    # P0-09, owner decision Oct 20, 2026: downloadable in the middle, the rest shuffled.
    header = [*COLUMNS, "downloadable"]
    order = [
        "title",
        "type",
        "downloadable",
        *reversed([c for c in COLUMNS if c not in ("title", "type")]),
    ]
    rows = load_manifest(
        write(
            corpus,
            reorder(PDF_ROW + ",", header, order),
            reorder(DOCX_ROW + ",true", header, order),
            reorder(SITE_ROW + ",", header, order),
            header=",".join(order),
        ),
        TAGS,
    )
    assert rows == load_manifest(
        write(corpus, PDF_ROW + ",", DOCX_ROW + ",true", SITE_ROW + ",", header=",".join(header)),
        TAGS,
    )
    assert [(r.type, r.metadata.title, r.metadata.downloadable) for r in rows] == [
        ("pdf", "Tidewater Outlook", False),
        ("docx", "Brightwater note", True),
        ("site", "Site", False),
    ]


@pytest.mark.parametrize("column", COLUMNS)
def test_missing_required_column_is_rejected(corpus: Path, column: str) -> None:
    header = [name for name in COLUMNS if name != column]
    row = reorder(PDF_ROW, list(COLUMNS), header)
    found = problems(write(corpus, row, header=",".join(header)))
    assert found == (f"line 1: header is missing required columns: {column}",)


def test_repeated_column_is_rejected(corpus: Path) -> None:
    found = problems(write(corpus, PDF_ROW + ",x", header=HEADER + ",notes"))
    assert found == ("line 1: columns listed more than once: notes",)


def test_empty_manifest_is_rejected(corpus: Path) -> None:
    [problem] = problems(write(corpus))
    assert problem.endswith("has no rows")


def test_problems_do_not_repeat_titles(corpus: Path) -> None:
    found = problems(write(corpus, PDF_ROW.replace(",public,", ",nope,")))
    assert all("Tidewater Outlook" not in p and "Fictional" not in p for p in found)


async def test_rows_run_in_order_and_a_failure_does_not_stop_the_rest(corpus: Path) -> None:
    rows = load_manifest(write(corpus, PDF_ROW, DOCX_ROW, SITE_ROW, PPTX_ROW), TAGS)
    seen: list[int] = []
    site_ids = [uuid4(), uuid4()]

    async def ingest_file(row: ManifestRow) -> IngestResult:
        seen.append(row.line)
        if row.type == "docx":
            return IngestResult(uuid4(), "failed", error_code="parse_failed")
        return IngestResult(uuid4(), "ingested", chunk_count=3)

    async def crawl_site(row: ManifestRow) -> tuple[str, list[IngestResult]]:
        seen.append(row.line)
        return "ok", [IngestResult(i, "ingested", chunk_count=2) for i in site_ids]

    ticks = iter(range(100))
    outcomes = await run_manifest(rows, ingest_file, crawl_site, clock=lambda: next(ticks))

    assert seen == [2, 3, 4, 5]
    assert [(o.line, o.status, o.chunk_count, o.error_code) for o in outcomes] == [
        (2, "ingested", 3, None),
        (3, "failed", 0, "parse_failed"),
        (4, "ok", 4, None),
        (5, "ingested", 3, None),
    ]
    assert outcomes[2].source_ids == tuple(site_ids)
    assert all(o.seconds == 1 for o in outcomes)


async def test_site_row_fails_when_the_crawl_or_a_page_fails(corpus: Path) -> None:
    [row] = load_manifest(write(corpus, SITE_ROW), TAGS)

    async def no_file(_: ManifestRow) -> IngestResult:
        raise AssertionError("not a file row")

    async def opted_out(_: ManifestRow) -> tuple[str, list[IngestResult]]:
        return "tdm_reserved", []

    async def one_page_failed(_: ManifestRow) -> tuple[str, list[IngestResult]]:
        return "ok", [
            IngestResult(uuid4(), "ingested", chunk_count=1),
            IngestResult(uuid4(), "failed", error_code="no_chunks"),
        ]

    [blocked] = await run_manifest([row], no_file, opted_out)
    [partial] = await run_manifest([row], no_file, one_page_failed)
    assert (blocked.status, blocked.error_code) == ("failed", "tdm_reserved")
    assert (partial.status, partial.error_code, partial.chunk_count) == ("failed", "no_chunks", 1)


async def test_a_site_row_waits_for_its_review_or_its_crawl(corpus: Path) -> None:
    # P1b-04: a site row registers the site; it waits for a reviewer or for the worker.
    [row] = load_manifest(write(corpus, SITE_ROW), TAGS)

    async def no_file(_: ManifestRow) -> IngestResult:
        raise AssertionError("not a file row")

    for status in ("proposed", "queued"):

        async def site(_: ManifestRow, status: str = status) -> tuple[str, list[IngestResult]]:
            return status, []

        [outcome] = await run_manifest([row], no_file, site)
        assert (outcome.status, outcome.error_code) == (status, None)

    async def rejected(_: ManifestRow) -> tuple[str, list[IngestResult]]:
        return "site_rejected", []

    [outcome] = await run_manifest([row], no_file, rejected)
    assert (outcome.status, outcome.error_code) == ("failed", "site_rejected")


async def test_rerun_is_idempotent_by_file_hash(env: tuple[Env, Ingest], corpus: Path) -> None:
    e, run = env
    rows = load_manifest(write(corpus, PDF_ROW, DOCX_ROW, PPTX_ROW), TAGS)

    async def ingest_file(row: ManifestRow) -> IngestResult:
        assert row.path is not None
        return await run(load_path(row.path), row.metadata)

    async def no_site(_: ManifestRow) -> tuple[str, list[IngestResult]]:
        raise AssertionError("no site rows")

    first = await run_manifest(rows, ingest_file, no_site)
    uploads = len(e.fake.uploads)
    second = await run_manifest(rows, ingest_file, no_site)

    assert [o.status for o in first] == ["ingested", "ingested", "ingested"]
    assert [o.status for o in second] == ["duplicate", "duplicate", "duplicate"]
    assert [o.source_ids for o in second] == [o.source_ids for o in first]
    assert len(e.fake.uploads) == uploads  # nothing uploaded again
    assert uploads == 4  # the DOCX went to both of its tags' datasets


async def test_rerun_with_a_new_tag_links_the_file_into_that_dataset(
    env: tuple[Env, Ingest], corpus: Path
) -> None:
    e, run = env

    async def ingest_file(row: ManifestRow) -> IngestResult:
        assert row.path is not None
        return await run(load_path(row.path), row.metadata)

    async def no_site(_: ManifestRow) -> tuple[str, list[IngestResult]]:
        raise AssertionError("no site rows")

    first = await run_manifest(load_manifest(write(corpus, PDF_ROW), TAGS), ingest_file, no_site)
    retag_row = PDF_ROW.replace(",sample-reports,", ",sample-reports;sample-web,")
    second = await run_manifest(load_manifest(write(corpus, retag_row), TAGS), ingest_file, no_site)
    assert [o.status for o in second] == ["retagged"]
    assert second[0].source_ids == first[0].source_ids
    assert [dataset for dataset, _, _ in e.fake.uploads] == [
        e.datasets["sample-reports"],
        e.datasets["sample-web"],
    ]


class _Client:
    async def __aenter__(self) -> _Client:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None


@pytest.fixture
def cli_env(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, Any]]:
    calls: list[tuple[Any, Any]] = []

    async def fake_ingest(_f: Any, _t: Any, source: Any, metadata: Any, **kw: Any) -> Any:
        calls.append((source, metadata))
        assert kw["content_root"] == Path("/srv/ask-spore/content")  # [files] content_root
        return IngestResult(source_id=uuid4(), status="ingested", chunk_count=2)

    monkeypatch.setattr(cli, "get_settings", lambda: load_settings(environ=ENV))
    monkeypatch.setattr(cli, "submit", fake_ingest)
    monkeypatch.setattr(cli.RagflowClient, "from_settings", staticmethod(lambda _: _Client()))
    return calls


def test_cli_invalid_manifest_uploads_nothing(
    cli_env: list[tuple[Any, Any]], corpus: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = write(corpus, PDF_ROW, PDF_ROW.replace(",public,", ",nope,"))
    with pytest.raises(SystemExit) as caught:
        cli.main(["ingest-manifest", str(manifest)])
    assert "line 3, licence_basis" in str(caught.value.code)
    assert cli_env == []  # the valid first row was not ingested either
    [logged] = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert (logged["event"], logged["count"]) == ("manifest.invalid", 1)


def test_cli_check_only_validates(
    cli_env: list[tuple[Any, Any]], corpus: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["ingest-manifest", str(write(corpus, PDF_ROW)), "--check"]) == 0
    assert cli_env == []
    assert '"event":"manifest.valid"' in capsys.readouterr().out.replace(" ", "")


def test_cli_ingests_and_logs_a_metadata_only_summary(
    cli_env: list[tuple[Any, Any]], corpus: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    summary = corpus / "summary.csv"
    manifest = write(corpus, PDF_ROW, DOCX_ROW)
    assert cli.main(["ingest-manifest", str(manifest), "--summary", str(summary)]) == 0

    assert [(s.filename, m.title) for s, m in cli_env] == [
        ("tidewater.pdf", "Tidewater Outlook"),
        ("brightwater.docx", "Brightwater note"),
    ]
    out = capsys.readouterr().out
    logged = [json.loads(line) for line in out.splitlines()]
    assert [line["event"] for line in logged] == [
        "manifest.valid",
        "ingest.result",
        "ingest.result",
        "manifest.row",
        "manifest.row",
        "manifest.summary",
    ]
    assert [line.get("manifest_line") for line in logged if line["event"] == "manifest.row"] == [
        2,
        3,
    ]
    assert logged[-1]["count"] == 2
    assert logged[-1]["chunk_count"] == 4
    for text in ("Tidewater", "Brightwater", "Fictional", "example.org", "tidewater.pdf"):
        assert text not in out
    with summary.open(encoding="utf-8") as handle:
        table = list(csv.DictReader(handle))
    assert [(r["line"], r["type"], r["status"], r["chunk_count"]) for r in table] == [
        ("2", "pdf", "ingested", "2"),
        ("3", "docx", "ingested", "2"),
    ]
    assert "Tidewater" not in summary.read_text(encoding="utf-8")


def test_cli_summary_counts_retagged_rows_separately(
    cli_env: list[tuple[Any, Any]],
    corpus: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    statuses = iter(["retagged", "duplicate"])

    async def fake_ingest(*_: Any, **__: Any) -> IngestResult:
        status = next(statuses)
        return IngestResult(
            source_id=uuid4(), status=status, chunk_count=3 * (status == "retagged")
        )

    monkeypatch.setattr(cli, "submit", fake_ingest)
    assert cli.main(["ingest-manifest", str(write(corpus, PDF_ROW, DOCX_ROW))]) == 0
    logged = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    totals = {
        line["status"]: (line["count"], line["chunk_count"])
        for line in logged
        if line["event"] == "manifest.summary"
    }
    assert totals == {"retagged": (1, 3), "duplicate": (1, 0)}


def test_write_summary_handles_site_rows(tmp_path: Path) -> None:
    ids = (uuid4(), uuid4())
    write_summary([RowOutcome(6, "site", "ok", 9, 12.34, ids)], tmp_path / "s.csv")
    [row] = list(csv.DictReader((tmp_path / "s.csv").read_text(encoding="utf-8").splitlines()))
    assert row["source_ids"] == f"{ids[0]};{ids[1]}"
    assert row["seconds"] == "12.3"


# --- P1a-14: the optional downloadable column ----------------------------------------------


def test_without_the_downloadable_column_nothing_is_downloadable(corpus: Path) -> None:
    rows = load_manifest(write(corpus, PDF_ROW, SITE_ROW), TAGS)
    assert [r.metadata.downloadable for r in rows] == [False, False]


def test_downloadable_column_is_read_per_row(corpus: Path) -> None:
    header = HEADER + ",downloadable"
    rows = load_manifest(
        write(
            corpus,
            PDF_ROW + ",",
            DOCX_ROW + ",true",
            PPTX_ROW + ",No",
            SITE_ROW + ",",
            header=header,
        ),
        TAGS,
    )
    assert [r.metadata.downloadable for r in rows] == [False, True, False, False]


def test_downloadable_column_values_are_checked(corpus: Path) -> None:
    header = HEADER + ",downloadable"
    found = problems(write(corpus, PDF_ROW + ",maybe", SITE_ROW + ",true", header=header))
    assert found == (
        "line 2, downloadable: must be true or false (empty means false)",
        "line 3, downloadable: only pdf, docx and pptx files can be downloadable",
    )


def test_unknown_extra_column_is_rejected(corpus: Path) -> None:
    [problem] = problems(write(corpus, PDF_ROW + ",x", header=HEADER + ",extra"))
    assert problem == "line 1: unknown columns: 'extra' (the only optional column is downloadable)"
    # Also in the middle, and also next to the optional column.
    header = ["extra", *COLUMNS[:4], "downloadable", *COLUMNS[4:]]
    row = reorder("x," + PDF_ROW + ",", ["extra", *COLUMNS, "downloadable"], header)
    [problem] = problems(write(corpus, row, header=",".join(header)))
    assert problem.startswith("line 1: unknown columns: 'extra'")


def test_cli_passes_the_downloadable_flag(cli_env: list[tuple[Any, Any]], corpus: Path) -> None:
    manifest = write(corpus, PDF_ROW + ",", DOCX_ROW + ",yes", header=HEADER + ",downloadable")
    assert cli.main(["ingest-manifest", str(manifest)]) == 0
    assert [m.downloadable for _, m in cli_env] == [False, True]


def test_cli_reports_queued_rows_and_settles_them_with_wait(
    cli_env: list[tuple[Any, Any]],
    corpus: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P1b-02: the CLI is a client of the queue; --wait reports what the jobs did."""
    job_ids: list[Any] = []

    async def queued(*_: Any, **__: Any) -> IngestResult:
        job_ids.append(uuid4())
        return IngestResult(source_id=uuid4(), status="queued", job_id=job_ids[-1])

    async def settled(_f: Any, results: Any) -> list[IngestResult]:
        assert [r.job_id for r in results] == job_ids
        return [
            IngestResult(r.source_id, "ingested", chunk_count=5, job_id=r.job_id, seconds=9.0)
            for r in results
        ]

    monkeypatch.setattr(cli, "submit", queued)
    monkeypatch.setattr(cli, "settle", settled)
    manifest = str(write(corpus, PDF_ROW, DOCX_ROW))
    assert cli.main(["ingest-manifest", manifest]) == 0
    logged = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert {line["status"] for line in logged if line["event"] == "manifest.row"} == {"queued"}

    job_ids.clear()
    assert cli.main(["ingest-manifest", manifest, "--wait"]) == 0
    logged = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    rows = [line for line in logged if line["event"] == "manifest.row"]
    assert [(r["status"], r["chunk_count"]) for r in rows] == [("ingested", 5), ("ingested", 5)]
    assert all(r["latency_ms"] >= 9000 for r in rows)  # the job's run time
