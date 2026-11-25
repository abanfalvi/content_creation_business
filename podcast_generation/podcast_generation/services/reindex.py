"""Rebuild the search index of sources that were indexed with an older embedding model or chunker.

    uv run python -m podcast_generation.services.reindex --dry-run    # list them
    uv run python -m podcast_generation.services.reindex              # rebuild them, one at a time

Until a source is rebuilt, searches over it find nothing. Each rebuild makes one model call per passage for
the neighbourhood summaries, plus the embeddings; the PDF or video is not processed again. Collections of
older versions are left on disk (they are not read any more) and can be deleted once everything is rebuilt.
"""
import argparse
import logging

from . import db, sources

log = logging.getLogger(__name__)


def warn_if_stale() -> None:
    """Say at startup which sources cannot be searched yet, and how to fix it."""
    stale = sources.stale_sources()
    if stale:
        log.warning(
            "%d source(s) were indexed with an older embedding model or chunker and cannot be searched until rebuilt: %s. "
            "Run: uv run python -m podcast_generation.services.reindex",
            len(stale), ", ".join(s["slug"] for s in stale),
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="only list the sources that need rebuilding")
    args = parser.parse_args(argv)

    db.init()  # no recover_interrupted(): the server may be running, and its sources in progress are not interrupted
    stale = sources.stale_sources()
    if not stale:
        print("Every source is indexed with the current embedding model and chunker.")
        return 0
    print(f"{len(stale)} source(s) to rebuild:")
    for s in stale:
        print(f"  {s['slug']}  ({s['title']})")
    if args.dry_run:
        return 0

    failed = 0
    for s in stale:
        print(f"\n== {s['slug']}")
        try:
            sources.reindex(s["slug"], on_stage=lambda label: print(f"   {label}"))
        except Exception as exc:  # noqa: BLE001 - keep going: one bad source must not block the others
            failed += 1
            print(f"   FAILED: {exc}")
        else:
            print("   done")
    print(f"\n{len(stale) - failed} rebuilt, {failed} failed.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
