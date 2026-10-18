import io
import time
import wave

import pytest

import fake_models
from app import create_app


def make_wav(seconds=1):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(8000)
        out.writeframes(b"\x00\x00" * 8000 * seconds)
    return buf.getvalue()


@pytest.fixture
def app(tmp_path, monkeypatch):
    fake_models.install(setter=lambda obj, name, value: monkeypatch.setattr(obj, name, value))
    return create_app(tmp_path)


@pytest.fixture
def client(app):
    return app.test_client()


def upload(client, name="Weekly sync.wav", data=None, context=""):
    return client.post(
        "/api/notes",
        data={"audio": (io.BytesIO(make_wav() if data is None else data), name), "context": context},
        content_type="multipart/form-data",
    )


def wait_for(client, note_id, statuses=("done", "failed"), timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        note = client.get(f"/api/notes/{note_id}").get_json()
        if note["status"] in statuses:
            return note
        time.sleep(0.05)
    raise AssertionError(f"Note {note_id} did not finish in {timeout}s: {note}")
