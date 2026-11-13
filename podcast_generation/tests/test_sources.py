from conftest import make_pdf, nb_url, wait_for

from podcast_generation.services import sources


def _fake_preprocess(calls):
    async def fake(title, author, pdf_path, end_page, on_stage=lambda s: None):
        calls.append((title, author, end_page))
        on_stage("Reading the PDF")
        return "ok"

    return fake


def upload(client, name="Deep_Work.pdf", data=None):
    return client.post(nb_url(client, "sources"), files=[("files", (name, data or make_pdf(4), "application/pdf"))])


def test_upload_is_registered_and_processed_in_the_background(client, monkeypatch):
    calls = []
    monkeypatch.setattr(sources, "preprocess_book", _fake_preprocess(calls))

    result = upload(client).json()[0]
    assert result["error"] is None
    assert result["source"]["title"] == "Deep Work"
    assert result["source"]["slug"] == "deep_work"
    assert result["source"]["pages"] == 4

    wait_for(lambda: client.get(nb_url(client, "sources")).json()[0]["status"] == "ready")
    assert calls == [("Deep Work", "", 4)]


def test_failed_ingestion_is_reported_and_can_be_retried_by_uploading_again(client, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("PDF parsing failed")

    monkeypatch.setattr(sources, "preprocess_book", boom)
    upload(client)
    failed = wait_for(lambda: next((s for s in client.get(nb_url(client, "sources")).json() if s["status"] == "failed"), None))
    assert "PDF parsing failed" in failed["error"]

    monkeypatch.setattr(sources, "preprocess_book", _fake_preprocess([]))
    assert upload(client).json()[0]["error"] is None  # a failed source may be replaced
    wait_for(lambda: client.get(nb_url(client, "sources")).json()[0]["status"] == "ready")


def test_rejects_non_pdf_corrupt_pdf_and_duplicates(client, monkeypatch):
    monkeypatch.setattr(sources, "preprocess_book", _fake_preprocess([]))

    assert "only PDF" in upload(client, "notes.txt", b"hello").json()[0]["error"]
    assert "not a readable PDF" in upload(client, "bad.pdf", b"not a pdf").json()[0]["error"]

    upload(client)
    wait_for(lambda: client.get(nb_url(client, "sources")).json()[0]["status"] == "ready")
    assert "already in your sources" in upload(client).json()[0]["error"]


def test_several_files_in_one_request(client, monkeypatch):
    monkeypatch.setattr(sources, "preprocess_book", _fake_preprocess([]))
    files = [("files", (n, make_pdf(), "application/pdf")) for n in ("A_Book.pdf", "Another-Book.pdf")]
    results = client.post(nb_url(client, "sources"), files=files).json()
    assert [r["source"]["slug"] for r in results] == ["a_book", "another-book"]
    wait_for(lambda: all(s["status"] == "ready" for s in client.get(nb_url(client, "sources")).json()))


def test_delete_source(client, monkeypatch):
    monkeypatch.setattr(sources, "preprocess_book", _fake_preprocess([]))
    upload(client)
    wait_for(lambda: client.get(nb_url(client, "sources")).json()[0]["status"] == "ready")
    assert client.delete("/api/sources/deep_work").status_code == 204
    assert client.get(nb_url(client, "sources")).json() == []
    assert client.delete("/api/sources/deep_work").status_code == 404
