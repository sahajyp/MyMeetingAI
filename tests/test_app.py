"""End-to-end tests of the Flask API with stand-in models."""

import io
import json

import engine
import fake_models
from app import create_app
from conftest import make_wav, upload, wait_for


def test_index_and_health(client):
    page = client.get("/")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "MyMeeting" in html and "New note" in html
    assert client.get("/health").get_json()["status"] == "ok"


def test_upload_validation(client):
    assert client.post("/api/notes", data={}, content_type="multipart/form-data").status_code == 400
    bad = upload(client, name="notes.txt", data=b"hello")
    assert bad.status_code == 400 and "supported" in bad.get_json()["error"]
    empty = upload(client, name="empty.wav", data=b"")
    assert empty.status_code == 400


def test_full_flow_creates_structured_notes(client):
    response = upload(client, context="Atlas launch team")
    assert response.status_code == 202
    note_id = response.get_json()["id"]

    note = wait_for(client, note_id)
    assert note["status"] == "done", note.get("error")
    assert note["progress"] == 100
    assert note["title"].startswith("Atlas Launch Sync")
    assert note["language"] == "en" and note["word_count"] > 200
    assert note["context"] == "Atlas launch team"
    assert note["has_audio"] is True
    assert len(note["transcript"]) == len(fake_models.SCRIPT)
    notes = note["notes"]
    assert notes["overview"] and notes["decisions"] and notes["action_items"] and notes["timeline"]

    listing = client.get("/api/notes").get_json()["notes"]
    assert [n["id"] for n in listing] == [note_id]
    assert "transcript" not in listing[0] and "notes" not in listing[0]


def test_exports(client):
    note_id = upload(client).get_json()["id"]
    wait_for(client, note_id)

    md = client.get(f"/api/notes/{note_id}/export?format=md")
    text = md.get_data(as_text=True)
    assert md.status_code == 200 and "attachment" not in md.headers.get("Content-Disposition", "")
    for heading in ("# Atlas Launch Sync", "## Overview", "## Key points", "## Decisions", "## Action items",
                    "## Discussion timeline", "## Open questions", "## Transcript"):
        assert heading in text
    assert "- [ ] Request production API keys from IT" in text and "Owner: Priya" in text

    download = client.get(f"/api/notes/{note_id}/export?format=md&download=1")
    assert download.headers["Content-Disposition"].startswith('attachment; filename="atlas-launch-sync')

    txt = client.get(f"/api/notes/{note_id}/export?format=txt").get_data(as_text=True)
    assert txt.splitlines()[0].startswith("Atlas Launch Sync") and "[00:00]" in txt
    assert json.loads(client.get(f"/api/notes/{note_id}/export?format=json").get_data())["id"] == note_id
    assert client.get(f"/api/notes/{note_id}/export?format=pdf").status_code == 400


def test_audio_supports_range_requests(client):
    note_id = upload(client, data=make_wav(2)).get_json()["id"]
    wait_for(client, note_id)
    full = client.get(f"/api/notes/{note_id}/audio")
    assert full.status_code == 200 and full.mimetype == "audio/wav"
    part = client.get(f"/api/notes/{note_id}/audio", headers={"Range": "bytes=0-99"})
    assert part.status_code == 206 and len(part.get_data()) == 100


def test_rename_keeps_custom_title_and_search_finds_notes(client):
    first = upload(client, name="one.wav").get_json()["id"]
    wait_for(client, first)

    renamed = client.patch(f"/api/notes/{first}", json={"title": "Board review"})
    assert renamed.status_code == 200 and renamed.get_json()["title"] == "Board review"
    assert client.patch(f"/api/notes/{first}", json={"title": "  "}).status_code == 400

    def search(q):
        return [n["id"] for n in client.get("/api/notes", query_string={"q": q}).get_json()["notes"]]

    assert search("board") == [first]            # title
    assert search("dashboard caching") == [first]  # transcript / notes text
    assert search("zzzz") == []
    assert search("100%") == []                    # LIKE wildcards are escaped

    # A rename must survive re-processing (custom titles are never overwritten).
    assert client.post(f"/api/notes/{first}/retry").status_code == 202
    assert wait_for(client, first)["title"] == "Board review"


def test_newest_notes_come_first(client):
    ids = []
    for name in ("a.wav", "b.wav", "c.wav"):
        ids.append(upload(client, name=name).get_json()["id"])
        wait_for(client, ids[-1])
    assert [n["id"] for n in client.get("/api/notes").get_json()["notes"]] == ids[::-1]


def test_delete_removes_note_and_audio(client, app):
    note_id = upload(client).get_json()["id"]
    wait_for(client, note_id)
    uploads = app.extensions["mymeeting"]["upload_dir"]
    assert len(list(uploads.iterdir())) == 1

    assert client.delete(f"/api/notes/{note_id}").status_code == 200
    assert list(uploads.iterdir()) == []
    assert client.get(f"/api/notes/{note_id}").status_code == 404
    assert client.get(f"/api/notes/{note_id}/audio").status_code == 404
    assert client.delete(f"/api/notes/{note_id}").status_code == 404


def test_failed_job_reports_error_and_can_be_retried(client, monkeypatch):
    monkeypatch.setattr(engine, "_get_whisper", lambda force_cpu=False: fake_models.FakeWhisper(segments=[]))
    note_id = upload(client).get_json()["id"]
    note = wait_for(client, note_id)
    assert note["status"] == "failed" and "No speech" in note["error"]

    fake_models.install(setter=lambda o, n, v: monkeypatch.setattr(o, n, v))
    assert client.post(f"/api/notes/{note_id}/retry").status_code == 202
    assert wait_for(client, note_id)["status"] == "done"


def test_unexpected_errors_are_reported_not_raised(client, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("model exploded")
    monkeypatch.setattr(engine, "_chat", boom)
    note = wait_for(client, upload(client).get_json()["id"])
    assert note["status"] == "failed" and "model exploded" in note["error"]


def test_retry_rules(client):
    assert client.post("/api/notes/doesnotexist/retry").status_code == 404
    note_id = upload(client).get_json()["id"]
    wait_for(client, note_id)
    assert client.get("/api/notes/doesnotexist").status_code == 404


def test_interrupted_notes_are_marked_failed_on_restart(tmp_path, monkeypatch):
    fake_models.install(setter=lambda o, n, v: monkeypatch.setattr(o, n, v))
    first = create_app(tmp_path)
    storage = first.extensions["mymeeting"]["storage"]
    storage.create("a" * 32, title="Stuck", filename="stuck.wav", audio_name="a.wav")
    storage.update("a" * 32, status="processing", stage="Transcribing audio", progress=20)

    second = create_app(tmp_path)  # simulates restarting the server
    note = second.test_client().get(f"/api/notes/{'a' * 32}").get_json()
    assert note["status"] == "failed" and "restarted" in note["error"]


def test_too_large_upload_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    fake_models.install(setter=lambda o, n, v: monkeypatch.setattr(o, n, v))
    small = create_app(tmp_path).test_client()
    response = upload(small, name="big.wav", data=make_wav(200))  # ~3 MB
    assert response.status_code == 413 and "limit" in response.get_json()["error"]
