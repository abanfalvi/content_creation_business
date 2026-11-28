"""The digest of a source is built once, and a combined source's digest is assembled from its sources' digests."""
import re

import pytest
from test_combined import write_source

from podcast_generation.agents.content_specialists.utils import get_book_path
from podcast_generation.book_preprocessing import combined, digest
from podcast_generation.book_preprocessing.digest import BookSynthesis, UnitDigest
from podcast_generation.book_preprocessing.source_meta import book_file
from podcast_generation.settings import DATA_DIR

WORK = "# Deep Work\n\nFocus is a skill.\nIt can be trained with practice.\n\n# Part Two\n\nSchedule every minute of the day.\n"
HABITS = "\n\n# Atomic Habits\n\nSmall changes compound over time.\nSystems beat goals every time.\n"  # leading blank lines
TALK = "Source: YouTube video\n\nA short talk.\n"
NUMBERED = re.compile(r"\[L(\d+)\] (.*)")


class FakeModel:
    """Stands in for ChatOpenRouter(...).with_structured_output(...): replies from the text it is shown.

    A section's claim quotes the first numbered line of the section and cites it. Every call is recorded with
    the title of the source it was about."""

    calls: list[tuple[str, str]] = []

    def __init__(self, *args, **kwargs):
        self.schema = None

    def with_structured_output(self, schema):
        self.schema = schema
        return self

    @staticmethod
    def _text(prompt) -> str:
        return prompt[-1][1]

    def _answer(self, prompt):
        text = self._text(prompt)
        title = re.search(r"Source: (.+?)(?: by .+)?\n", text).group(1)
        FakeModel.calls.append((self.schema.__name__, title))
        if self.schema is BookSynthesis:
            return BookSynthesis(
                thesis=f"Thesis of {title}", structure=f"{title} is built in parts, see L7-9.", central_frameworks=[f"Framework of {title}"],
                author_voice=f"Voice of {title}", objections=f"{title} answers objections near L3.")
        number, line = NUMBERED.search(text).groups()
        return UnitDigest(
            summary=f"Summary of {title}, starting at L{number}.", claims=[{"text": line, "line": int(number)}],
            voice_quotes=[{"text": line, "line": int(number)}])

    async def abatch(self, prompts, config=None, return_exceptions=False):
        return [self._answer(p) for p in prompts]

    async def ainvoke(self, prompt):
        return self._answer(prompt)


@pytest.fixture(autouse=True)
def model(monkeypatch):
    FakeModel.calls = []
    monkeypatch.setattr(digest, "ChatOpenRouter", FakeModel)
    for slug in ("deep_work", "atomic_habits", "ted_talk"):  # the data folder is shared by every test
        for name in (digest.DIGEST_FILENAME, digest.DIGEST_DATA_FILENAME):
            (DATA_DIR / slug / name).unlink(missing_ok=True)
    return FakeModel


def sources(*which):
    rows = {
        "deep_work": {"slug": "deep_work", "title": "Deep Work", "author": "Cal Newport", "indexed": 1},
        "atomic_habits": {"slug": "atomic_habits", "title": "Atomic Habits", "author": "", "indexed": 1},
        "ted_talk": {"slug": "ted_talk", "title": "Ted Talk", "author": "A speaker", "indexed": 0},
    }
    return [rows[w] for w in which]


def prepare(*which):
    write_source("deep_work", WORK)
    write_source("atomic_habits", HABITS)
    write_source("ted_talk", TALK)
    return combined.prepare_combined_source(sources(*which))


def calls_for(title):
    return [kind for kind, t in FakeModel.calls if t == title]


def digest_text(slug):
    return (DATA_DIR / slug / digest.DIGEST_FILENAME).read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_a_source_is_digested_into_markdown_and_the_data_it_is_rendered_from():
    write_source("deep_work", WORK)

    message = await digest.digest_book("Deep Work")

    assert "written" in message
    assert (DATA_DIR / "deep_work" / digest.DIGEST_DATA_FILENAME).exists()
    text = digest_text("deep_work")
    assert "# Source digest: Deep Work" in text and "Thesis of Deep Work" in text and "- # Deep Work [L1]" in text
    assert "up to date" in await digest.digest_book("Deep Work")  # unchanged: no second build
    assert calls_for("Deep Work").count("BookSynthesis") == 1


@pytest.mark.asyncio
async def test_a_combined_digest_has_one_block_per_source_with_citations_in_the_combined_files_numbers():
    slug, title = prepare("deep_work", "atomic_habits")

    message = await digest.digest_book(title)

    assert "assembled from 2 sources (2 digested now)" in message
    text = digest_text(slug)
    assert text.index("# Source 1 of 2: Deep Work (Cal Newport)") < text.index("# Source 2 of 2: Atomic Habits")
    assert "Thesis of Deep Work" in text and "Thesis of Atomic Habits" in text and text.count("## Thesis") == 2  # a thesis each
    lines = book_file(slug).read_text(encoding="utf-8").splitlines()
    block = {n: part for n, part in enumerate(re.split(r"^# Source \d of 2: ", text, flags=re.M)[1:], start=1)}
    for n in (1, 2):
        cited = re.findall(r"- (.+?) \[L(\d+)\]", block[n])  # every claim and quote the block cites
        assert cited
        for claim, number in cited:  # the fake model's claims quote the line they cite: it must be there in the combined file
            assert lines[int(number) - 1].strip() == claim.strip('"'), (claim, number)
    # the second source had blank lines cut from its top and sits after the first: its first line is still found
    atomic_claim = re.search(r"- (# Atomic Habits) \[L(\d+)\]", block[2])
    assert lines[int(atomic_claim.group(2)) - 1] == "# Atomic Habits"


@pytest.mark.asyncio
async def test_line_references_the_model_wrote_in_prose_move_with_the_source():
    slug, title = prepare("deep_work", "atomic_habits")
    await digest.digest_book(title)
    text = digest_text(slug)
    shift = {m["slug"]: m["shift"] for m in combined.members_of(slug)}

    assert shift["deep_work"] > 0 and shift["atomic_habits"] > shift["deep_work"]  # both sit below the combined file's index
    for source, title in (("deep_work", "Deep Work"), ("atomic_habits", "Atomic Habits")):
        moved = shift[source]
        assert f"{title} is built in parts, see L{7 + moved}-{9 + moved}." in text  # the model wrote "L7-9" of its own file
        assert f"{title} answers objections near L{3 + moved}." in text
    # a source's first numbered line is L1 (Deep Work) or L3 (Atomic Habits, which has two blank lines above it)
    assert f"Summary of Deep Work, starting at L{1 + shift['deep_work']}" in text
    assert f"Summary of Atomic Habits, starting at L{3 + shift['atomic_habits']}" in text


@pytest.mark.asyncio
async def test_a_source_is_only_digested_once_whatever_it_is_combined_with(model):
    slug_ab, title_ab = prepare("deep_work", "atomic_habits")
    await digest.digest_book(title_ab)
    assert calls_for("Deep Work") and calls_for("Atomic Habits")
    model.calls.clear()

    # the same set again: nothing is built
    assert "(0 digested now)" in await digest.digest_book(title_ab)
    assert model.calls == []

    # another combination with one of them, in another order: only the new source is digested
    write_source("ted_talk", "# Third\n\nA third source.\n")
    rows = sources("ted_talk")
    rows[0]["indexed"] = 1
    slug_ca, title_ca = combined.prepare_combined_source(rows + sources("deep_work"))
    assert slug_ca != slug_ab
    assert "(1 digested now)" in await digest.digest_book(title_ca)
    assert calls_for("Deep Work") == [] and calls_for("Ted Talk") != []

    # and the source on its own reuses the same digest
    assert "up to date" in await digest.digest_book("Deep Work")
    assert calls_for("Deep Work") == []


@pytest.mark.asyncio
async def test_a_changed_source_is_digested_again_in_every_combination(model):
    _, title = prepare("deep_work", "atomic_habits")
    await digest.digest_book(title)
    model.calls.clear()

    write_source("atomic_habits", HABITS + "A new final paragraph.\n")
    _, title = combined.prepare_combined_source(sources("deep_work", "atomic_habits"))
    assert "(1 digested now)" in await digest.digest_book(title)
    assert calls_for("Deep Work") == [] and calls_for("Atomic Habits") != []


@pytest.mark.asyncio
async def test_a_short_transcript_has_no_digest_and_is_pointed_to_by_its_lines(model):
    slug, title = prepare("deep_work", "ted_talk")

    message = await digest.digest_book(title)

    assert "(1 digested now)" in message and calls_for("Ted Talk") == []
    member = next(m for m in combined.members_of(slug) if m["slug"] == "ted_talk")
    text = digest_text(slug)
    assert "# Source 2 of 2: Ted Talk (A speaker)" in text
    assert f"Read it whole, at lines {member['start']}-{member['end']} of this file." in text


@pytest.mark.asyncio
async def test_a_digest_written_before_the_data_was_kept_is_built_again_once(model):
    write_source("deep_work", WORK)
    await digest.digest_book("Deep Work")
    (DATA_DIR / "deep_work" / digest.DIGEST_DATA_FILENAME).unlink()  # what an older run left: the markdown alone
    model.calls.clear()
    _, title = prepare("deep_work", "atomic_habits")

    await digest.digest_book(title)

    assert calls_for("Deep Work") != [] and get_book_path("Deep Work") == "deep_work"
