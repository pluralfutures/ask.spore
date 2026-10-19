"""P0-17: mapping file-name source references to canonical URLs (synthetic names)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from eval import sources
from eval.cli import main
from eval.sources import manifest_urls, map_sources, parse_aliases, shared_url_paths

MANIFEST = (
    "path,url,type,tags,title,publisher,published_on,canonical_url,licence_basis,"
    "language,max_pages,notes\n"
    "reports/[A] Tidewater 2026.pdf,,pdf,sample-reports,T,P,2026,https://ex.org/t,public,,,\n"
    'reports/b/Kestrel, deck.pptx,,pptx,sample-reports,K,P,2026,https://ex.org/k,public,,,"x"\n'
    "reports/Kestrel copy.pdf,,pdf,sample-reports,K,P,2026,https://ex.org/k,public,,,\n"
    "analysis/own.docx,,docx,sample-analysis,O,Us,2026,,own-work,,,\n"
    ",https://site.ex/,site,sample-web,S,S,2026,https://site.ex/,public,,5,\n"
).replace("reports/b/Kestrel, deck.pptx", '"reports/b/Kestrel, deck.pptx"')
UUID = "0b8c5d3e-1f2a-4b6c-9d7e-8f9a0b1c2d3e"


def item(id_: str, *refs: str, type_: str = "factual") -> str:
    return json.dumps(
        {
            "id": id_,
            "question": "Q?",
            "type": type_,
            "expected_source_ids": list(refs),
            "expected_answer_notes": "n",
            "labels": [],
        }
    )


def test_manifest_urls_use_file_names_and_skip_rows_without_a_link() -> None:
    assert manifest_urls(MANIFEST) == {
        "[A] Tidewater 2026.pdf": "https://ex.org/t",
        "Kestrel, deck.pptx": "https://ex.org/k",
        "Kestrel copy.pdf": "https://ex.org/k",
    }


def test_names_become_urls_and_urls_and_uuids_pass_through() -> None:
    urls = manifest_urls(MANIFEST)
    text = "\n".join(
        [
            item("a", "[A] Tidewater 2026.pdf", "Kestrel, deck.pptx"),
            item("b", "https://other.ex/x", UUID),
            "",
            item("c", "Kestrel, deck.pptx", "Kestrel copy.pdf"),  # same canonical URL
            item("d", type_="out_of_corpus"),
        ]
    )
    out = map_sources(text, urls)
    assert out.problems == []
    refs = [json.loads(line)["expected_source_ids"] for line in out.lines]
    assert refs == [
        ["https://ex.org/t", "https://ex.org/k"],
        ["https://other.ex/x", UUID],
        ["https://ex.org/k"],
        [],
    ]
    assert json.loads(out.lines[0])["question"] == "Q?"  # other fields unchanged


def test_unknown_names_are_reported_not_guessed() -> None:
    out = map_sources(item("a", "[A] Tidewater 2025.pdf"), manifest_urls(MANIFEST))
    assert out.problems == ["line 1 (a): no manifest file named '[A] Tidewater 2025.pdf'"]


def test_aliases_map_a_name_to_a_manifest_file() -> None:
    aliases = parse_aliases(["[B] Tidewater 2026.pdf=[A] Tidewater 2026.pdf", "gone.pdf=x.pdf"])
    out = map_sources(item("a", "[B] Tidewater 2026.pdf"), manifest_urls(MANIFEST), aliases)
    assert json.loads(out.lines[0])["expected_source_ids"] == ["https://ex.org/t"]
    assert out.aliased == 1
    assert out.problems == ["alias not used: 'gone.pdf'"]


def test_alias_without_equals_is_rejected() -> None:
    with pytest.raises(ValueError):
        parse_aliases(["just-a-name.pdf"])


def test_cli_writes_only_when_every_name_maps(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.csv"
    manifest.write_text(MANIFEST, encoding="utf-8-sig")
    source = tmp_path / "set.jsonl"
    output = tmp_path / "v1.jsonl"
    source.write_text(item("a", "[A] Tidewater 2025.pdf") + "\n", encoding="utf-8")
    argv = ["map-sources", str(source), "--manifest", str(manifest), "-o", str(output)]

    assert main(argv) == 1
    assert not output.exists()
    assert main([*argv, "--alias", "[A] Tidewater 2025.pdf=[A] Tidewater 2026.pdf"]) == 0
    [line] = output.read_text(encoding="utf-8").splitlines()
    assert json.loads(line)["expected_source_ids"] == ["https://ex.org/t"]


def test_shared_url_paths_lists_files_whose_link_is_shared() -> None:
    assert shared_url_paths(MANIFEST) == {
        "Kestrel, deck.pptx": "reports/b/Kestrel, deck.pptx",
        "Kestrel copy.pdf": "reports/Kestrel copy.pdf",
    }


def test_shared_url_files_map_to_register_uuids() -> None:
    text = "\n".join(
        [item("a", "[A] Tidewater 2026.pdf", "Kestrel copy.pdf"), item("b", "Kestrel, deck.pptx")]
    )
    shared = frozenset(shared_url_paths(MANIFEST))
    other = "1d2c3b4a-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
    uuids = {"Kestrel copy.pdf": UUID, "Kestrel, deck.pptx": other}
    out = map_sources(text, manifest_urls(MANIFEST), shared=shared, uuid_by_name=uuids)
    refs = [json.loads(line)["expected_source_ids"] for line in out.lines]
    assert refs == [["https://ex.org/t", UUID], [other]]  # unshared URL kept
    assert out.by_uuid == {"a": ["Kestrel copy.pdf"], "b": ["Kestrel, deck.pptx"]}
    assert out.shared_url == 2


def test_shared_url_file_missing_from_the_register_is_a_problem() -> None:
    shared = frozenset(shared_url_paths(MANIFEST))
    out = map_sources(
        item("a", "Kestrel copy.pdf"), manifest_urls(MANIFEST), shared=shared, uuid_by_name={}
    )
    assert out.problems == [
        "line 1 (a): 'Kestrel copy.pdf' shares its canonical URL and has no ingested source "
        "in the register"
    ]


def test_without_register_shared_urls_are_kept_and_counted() -> None:
    shared = frozenset(shared_url_paths(MANIFEST))
    out = map_sources(item("a", "Kestrel copy.pdf"), manifest_urls(MANIFEST), shared=shared)
    assert json.loads(out.lines[0])["expected_source_ids"] == ["https://ex.org/k"]
    assert (out.shared_url, out.by_uuid) == (1, {})


def test_cli_looks_up_shared_files_by_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = tmp_path / "manifest.csv"
    manifest.write_text(MANIFEST, encoding="utf-8-sig")
    (tmp_path / "reports" / "b").mkdir(parents=True)
    (tmp_path / "reports" / "Kestrel copy.pdf").write_bytes(b"copy")
    (tmp_path / "reports" / "b" / "Kestrel, deck.pptx").write_bytes(b"deck")
    source = tmp_path / "set.jsonl"
    source.write_text(item("a", "Kestrel copy.pdf") + "\n", encoding="utf-8")
    output = tmp_path / "v1.jsonl"
    asked: list[list[str]] = []

    async def fake_register(url: str, hashes: list[str]) -> dict[str, str]:
        assert url == "postgresql://ro@db/x"
        asked.append(hashes)
        return {hashlib.sha256(b"copy").hexdigest(): UUID}

    monkeypatch.setenv("DATABASE_URL", "postgresql://ro@db/x")
    monkeypatch.setattr(sources, "register_ids", fake_register)
    argv = ["map-sources", str(source), "--manifest", str(manifest), "-o", str(output)]
    assert main([*argv, "--uuid-for-shared-urls"]) == 0

    assert sorted(asked[0]) == sorted(hashlib.sha256(b).hexdigest() for b in (b"copy", b"deck"))
    assert json.loads(output.read_text(encoding="utf-8"))["expected_source_ids"] == [UUID]
    assert "a: 1 entry" in capsys.readouterr().out
