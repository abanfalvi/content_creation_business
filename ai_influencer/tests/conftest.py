"""Test-session setup shared by everything under tests/.

A handful of project modules do real work at *import* time — src/memory_store.py
opens a live Postgres connection and calls .setup(), and src/models.py calls
opik.configure(...), which makes a network request to validate the workspace.
That's fine for the running app (both are meant to happen once, lazily), but
it means simply importing an agent module — even just to unit-test a plain
tool function — would otherwise require live Postgres/Opik access. Stubbing
both here, before any test module imports project code, keeps the test suite
fast, deterministic, and runnable offline/in CI.

Several tools/agents also load files (e.g. SYSTEM_PROMPT.md) via paths that
are relative to the project root, so tests must run with that as the cwd.
"""
import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

if "src.memory_store" not in sys.modules:
    _fake_memory_store = types.ModuleType("src.memory_store")

    class _FakeStore:
        """Stands in for the real PostgresStore in tests — nothing under
        tests/ should depend on the long-term memory store actually
        persisting anything."""

        def get(self, *args, **kwargs):
            return None

        def put(self, *args, **kwargs):
            return None

        def delete(self, *args, **kwargs):
            return None

        def search(self, *args, **kwargs):
            return []

        def setup(self):
            return None

    _fake_memory_store.shared_memory_store = _FakeStore()
    # src/self_evolution.py imports `shared_store` (not `shared_memory_store`)
    # from this module — that name doesn't actually exist in the real
    # src/memory_store.py (a real bug there, flagged separately), but the
    # stub still needs to provide it so importing anything that chains
    # through auditor/tools.py -> self_evolution doesn't fail here too.
    _fake_memory_store.shared_store = _fake_memory_store.shared_memory_store
    sys.modules["src.memory_store"] = _fake_memory_store

import opik  # noqa: E402

opik.configure = lambda *args, **kwargs: None
