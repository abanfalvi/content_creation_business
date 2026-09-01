"""Deterministic unit tests for check_previous_influencers_persona — the
shared helper behind each Persona & Identity specialist's
check_existing_influencers tool. No LLM call involved: this only reads
directories and a (faked) store."""
from src.agents.persona_identity.utils import check_previous_influencers_persona


class _StoreItem:
    def __init__(self, value):
        self.value = value


class _FakeStore:
    """Stands in for the real shared_memory_store — enough to exercise
    .get(namespace, key) the way content_production's read_persona_info
    already populates it."""

    def __init__(self, data=None):
        self._data = data or {}

    def get(self, namespace, key):
        value = self._data.get((namespace, key))
        return _StoreItem(value) if value is not None else None

    def put(self, namespace, key, value):
        self._data[(namespace, key)] = value


def _make_influencer_dir(tmp_path, name):
    (tmp_path / "src" / "influencers" / name).mkdir(parents=True)


def test_no_other_influencers_exist(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = check_previous_influencers_persona("new_influencer", _FakeStore())
    assert "No other influencers exist yet" in result


def test_current_influencer_is_excluded_from_comparison(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _make_influencer_dir(tmp_path, "the_one_being_designed")
    result = check_previous_influencers_persona("the_one_being_designed", _FakeStore())
    assert "No other influencers exist yet" in result


def test_other_influencers_without_summaries_are_noted_but_not_dumped(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _make_influencer_dir(tmp_path, "mia")
    _make_influencer_dir(tmp_path, "zoe")
    result = check_previous_influencers_persona(None, _FakeStore())
    assert "mia" in result and "zoe" in result
    assert "none have a summarized persona yet" in result


def test_returns_summarized_sections_for_other_influencers(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _make_influencer_dir(tmp_path, "mia")
    _make_influencer_dir(tmp_path, "new_one")
    store = _FakeStore({
        (("content_production", "mia"), "character"): {"archetype": "cozy homebody"},
        (("content_production", "mia"), "personality"): {"core_values": ["consistency over intensity"]},
    })

    result = check_previous_influencers_persona("new_one", store)

    assert "## mia" in result
    assert "CHARACTER" in result and "cozy homebody" in result
    assert "PERSONALITY" in result and "consistency over intensity" in result
    assert "BACKSTORY" not in result  # nothing stored for it, shouldn't be fabricated
    assert "new_one" not in result  # the influencer being designed excludes itself
