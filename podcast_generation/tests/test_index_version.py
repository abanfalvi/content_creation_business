"""The index records what built it (embedding model, chunker); a source built by an older one is rebuilt."""
import asyncio
import logging
import re

import pytest

from podcast_generation.book_preprocessing import index_version, pipeline, source_meta
from podcast_generation.book_preprocessing.embeddings import EMBEDDING_MAX_TOKENS
from podcast_generation.book_preprocessing.index_version import CHUNK_SIZE, INDEX_VERSION, collection_name
from podcast_generation.services import db, reindex, sources


# --- passages must fit the embedding model --------------------------------------------------------

def test_a_passage_fits_the_embedding_models_context():
    # An embedding model silently ignores what is past its context (all-minilm-l6-v2 read ~256 tokens of each
    # ~500-token passage). Two characters per token is far below real English, so this is a safe upper bound.
    assert CHUNK_SIZE / 2 <= EMBEDDING_MAX_TOKENS


# --- collections are named after the version -------------------------------------------------------

def test_collection_names_follow_the_index_version():
    a = collection_name("books", "model-a|chunk-2048|v1")
    assert a == collection_name("books", "model-a|chunk-2048|v1")
    assert a != collection_name("books", "model-b|chunk-2048|v1")  # another model: another collection
    assert a != collection_name("books", "model-a|chunk-512|v1")   # another chunker: another collection
    assert a != collection_name("books_level_summaries", "model-a|chunk-2048|v1")
    assert re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{1,510}[A-Za-z0-9]", a)  # what Chroma accepts
    assert collection_name("books") == collection_name("books", INDEX_VERSION)


def test_the_version_names_the_model_and_the_chunk_size():
    assert index_version.EMBEDDING_MODEL in INDEX_VERSION and str(CHUNK_SIZE) in INDEX_VERSION


# --- stale detection ---------------------------------------------------------------------------------

def make_source(slug, **meta):
    source_meta.book_file(slug).parent.mkdir(parents=True, exist_ok=True)
    source_meta.book_file(slug).write_text("text", encoding="utf-8")
    source_meta.write_meta(slug, kind="pdf", title=slug, indexed=True, **meta)


def test_a_source_without_a_recorded_version_is_stale():
    make_source("iv_legacy")  # indexed before versions were recorded
    assert source_meta.index_is_stale("iv_legacy")


def test_a_source_is_stale_only_for_a_different_version():
    make_source("iv_other", index_version="older-model|chunk-2048|v1")
    assert source_meta.index_is_stale("iv_other")
    make_source("iv_current", index_version=INDEX_VERSION)
    assert not source_meta.index_is_stale("iv_current")


def test_unindexed_sources_and_sources_without_text_are_never_stale():
    make_source("iv_short")
    source_meta.update_meta("iv_short", indexed=False)  # a short transcript is read whole
    assert not source_meta.index_is_stale("iv_short")
    source_meta.write_meta("iv_gone", kind="pdf", title="gone", indexed=True)  # no text file to rebuild from
    assert not source_meta.index_is_stale("iv_gone")


def test_update_meta_adds_to_what_is_there_and_write_meta_starts_over():
    source_meta.write_meta("iv_meta", kind="pdf", title="T", indexed=True)
    source_meta.update_meta("iv_meta", index_version="v")
    assert source_meta.read_meta("iv_meta") == {"kind": "pdf", "title": "T", "indexed": True, "index_version": "v"}
    source_meta.write_meta("iv_meta", kind="pdf", title="T", indexed=True)
    assert "index_version" not in source_meta.read_meta("iv_meta")


# --- ingestion records the version -----------------------------------------------------------------

def test_ingesting_a_book_records_the_version_once_it_is_indexed(monkeypatch):
    events = []

    async def fake_parse(path, out):
        open(out, "w", encoding="utf-8").write("text")

    async def fake_index(md_path, title, author, on_stage):
        # While indexing, the version is not recorded yet: a crash here must leave the source stale.
        events.append(source_meta.read_meta("iv_book").get("index_version"))

    monkeypatch.setattr(pipeline, "parse_pdf", fake_parse)
    monkeypatch.setattr(pipeline, "_index", fake_index)
    asyncio.run(pipeline.preprocess_book("IV Book", "Author", "x.pdf", 3))
    assert events == [None]
    assert source_meta.read_meta("iv_book")["index_version"] == INDEX_VERSION
    assert not source_meta.index_is_stale("iv_book")


def test_a_failed_index_leaves_the_source_stale(monkeypatch):
    make_source("iv_fail", index_version="older-model|chunk-2048|v1")

    async def boom(*a, **k):
        raise RuntimeError("embedding API down")

    monkeypatch.setattr(pipeline, "_index", boom)
    with pytest.raises(RuntimeError):
        asyncio.run(pipeline.reindex_source("iv_fail", "T", "A"))
    assert source_meta.index_is_stale("iv_fail")


def test_reindex_source_rebuilds_from_the_stored_text(monkeypatch):
    make_source("iv_rebuild")
    seen = []

    async def fake_index(md_path, title, author, on_stage):
        seen.append((md_path.read_text(encoding="utf-8"), title, author))

    monkeypatch.setattr(pipeline, "_index", fake_index)
    asyncio.run(pipeline.reindex_source("iv_rebuild", "Title", "Author"))
    assert seen == [("text", "Title", "Author")]
    assert not source_meta.index_is_stale("iv_rebuild")


def test_reindex_source_without_a_text_file_says_so():
    with pytest.raises(FileNotFoundError):
        asyncio.run(pipeline.reindex_source("iv_nothing_here", "T", "A"))


# --- rebuilding through the sources service ---------------------------------------------------------

def add_row(slug, status="ready", indexed=1, kind="pdf", author=""):
    db.insert("sources", {
        "slug": slug, "notebook_id": None, "title": slug.title(), "filename": f"{slug}.pdf", "pdf_path": "", "pages": 3,
        "status": status, "stage": "", "error": "", "created_at": db.now(), "kind": kind, "url": "", "author": author,
        "duration": 0, "indexed": indexed,
    })


def test_only_ready_indexed_sources_with_an_old_index_are_listed(client):
    for slug in ("iv_s_stale", "iv_s_current", "iv_s_failed", "iv_s_short"):
        make_source(slug, **({"index_version": INDEX_VERSION} if slug == "iv_s_current" else {}))
    add_row("iv_s_stale")
    add_row("iv_s_current")
    add_row("iv_s_failed", status="failed")
    add_row("iv_s_short", indexed=0)
    assert [s["slug"] for s in sources.stale_sources()] == ["iv_s_stale"]


def test_reindex_runs_the_rebuild_and_leaves_the_source_ready(client, monkeypatch):
    make_source("iv_run")
    add_row("iv_run", author="Writer")
    calls, stages = [], []

    async def fake_reindex(slug, title, author, on_stage):
        calls.append((slug, title, author, db.one("SELECT status FROM sources WHERE slug = ?", [slug])["status"]))
        on_stage("Indexing passages")

    monkeypatch.setattr(sources, "reindex_source", fake_reindex)
    sources.reindex("iv_run", on_stage=stages.append)
    assert calls == [("iv_run", "Iv_Run", "Writer", "processing")]  # shown as processing while it runs
    assert stages == ["Indexing passages"]
    row = sources.get_source("iv_run")
    assert (row["status"], row["stage"], row["error"]) == ("ready", "", "")


def test_a_failed_rebuild_keeps_the_source_ready_and_stale_so_it_can_be_retried(client, monkeypatch):
    make_source("iv_retry")
    add_row("iv_retry")

    async def boom(*a, **k):
        raise RuntimeError("embedding API down")

    monkeypatch.setattr(sources, "reindex_source", boom)
    with pytest.raises(RuntimeError, match="embedding API down"):
        sources.reindex("iv_retry")
    assert sources.get_source("iv_retry")["status"] == "ready"
    assert [s["slug"] for s in sources.stale_sources()] == ["iv_retry"]


def test_reindex_ignores_a_source_that_is_not_ready(client, monkeypatch):
    make_source("iv_busy")
    add_row("iv_busy", status="processing")

    async def fail(*a, **k):
        raise AssertionError("must not rebuild a source that is being processed")

    monkeypatch.setattr(sources, "reindex_source", fail)
    sources.reindex("iv_busy")


# --- telling the operator ----------------------------------------------------------------------------

def test_startup_names_the_sources_that_cannot_be_searched(client, caplog):
    make_source("iv_warn")
    add_row("iv_warn")
    with caplog.at_level(logging.WARNING):
        reindex.warn_if_stale()
    assert "iv_warn" in caplog.text and "services.reindex" in caplog.text


def test_startup_is_quiet_when_every_index_is_current(client, caplog):
    make_source("iv_quiet", index_version=INDEX_VERSION)
    add_row("iv_quiet")
    with caplog.at_level(logging.WARNING):
        reindex.warn_if_stale()
    assert "iv_quiet" not in caplog.text


def test_the_command_lists_then_rebuilds(client, monkeypatch, capsys):
    monkeypatch.setattr(reindex.db, "init", lambda *a, **k: None)  # keep the test database
    make_source("iv_cli")
    add_row("iv_cli")
    rebuilt = []

    async def fake_reindex(slug, title, author, on_stage):
        rebuilt.append(slug)
        source_meta.update_meta(slug, index_version=INDEX_VERSION)

    monkeypatch.setattr(sources, "reindex_source", fake_reindex)

    assert reindex.main(["--dry-run"]) == 0
    assert "iv_cli" in capsys.readouterr().out and rebuilt == []

    assert reindex.main([]) == 0
    assert rebuilt == ["iv_cli"]

    assert reindex.main([]) == 0
    assert "current embedding model" in capsys.readouterr().out.splitlines()[-1]
    assert rebuilt == ["iv_cli"]  # nothing left to rebuild
