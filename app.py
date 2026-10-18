"""MyMeeting - turn meeting recordings into structured notes.

Run:
    pip install -r requirements.txt
    python app.py              # http://localhost:5000

Everything runs on your own machine: audio is transcribed with Whisper and the
notes are written by an open-source LLM. Nothing is sent to a third party.
"""

import logging
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request, send_file

import engine
import exporter
from storage import Storage

log = logging.getLogger("mymeeting")

BASE_DIR = Path(__file__).resolve().parent

ALLOWED_EXTENSIONS = (
    ".mp3", ".wav", ".m4a", ".mp4", ".webm", ".ogg", ".oga", ".opus", ".flac",
    ".aac", ".wma", ".mpeg", ".mpga", ".mkv", ".mov", ".3gp", ".amr",
)
AUDIO_MIME = {
    ".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4", ".mp4": "video/mp4",
    ".webm": "audio/webm", ".ogg": "audio/ogg", ".oga": "audio/ogg", ".opus": "audio/ogg",
    ".flac": "audio/flac", ".aac": "audio/aac",
}
PUBLIC_LIST_FIELDS = (
    "id", "title", "filename", "status", "stage", "progress", "error",
    "created_at", "duration", "language", "word_count",
)


class JobCancelled(Exception):
    """The note was deleted while it was being processed."""


def create_app(data_dir=None):
    data_dir = Path(data_dir or os.environ.get("DATA_DIR") or BASE_DIR / "data")
    upload_dir = data_dir / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    max_mb = int(os.environ.get("MAX_UPLOAD_MB", "300"))
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = max_mb * 1024 * 1024

    storage = Storage(data_dir / "mymeeting.db")
    storage.mark_interrupted()
    # One worker: the models are big, so recordings are processed one at a time.
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mymeeting-worker")
    app.extensions["mymeeting"] = {"storage": storage, "executor": executor, "upload_dir": upload_dir}

    # ------------------------------------------------------------- helpers
    def error(message, status=400):
        return jsonify(error=message), status

    def public(note, full=False):
        out = {key: note.get(key) for key in PUBLIC_LIST_FIELDS}
        if full:
            audio = upload_dir / note["audio_name"] if note.get("audio_name") else None
            out.update(
                context=note.get("context", ""),
                transcript=note.get("transcript") or [],
                notes=note.get("notes"),
                has_audio=bool(audio and audio.exists()),
            )
        return out

    def friendly_error(exc):
        if isinstance(exc, engine.NoSpeechError):
            return str(exc)
        message = f"{type(exc).__name__}: {exc}"
        if "Invalid data found" in message or "InvalidDataError" in message:
            return "This file couldn't be read as audio. Convert it to MP3 or WAV and upload it again."
        return message[:400]

    # ----------------------------------------------------------- background job
    def run_job(note_id):
        note = storage.get(note_id, full=True)
        if note is None:  # deleted while queued
            return
        audio_path = upload_dir / (note["audio_name"] or "")
        last = {"pct": -1.0, "stage": None}

        def report(pct, stage):
            pct = round(min(max(pct, 0.0), 99.0), 1)
            if stage == last["stage"] and pct - last["pct"] < 1:
                return
            last.update(pct=pct, stage=stage)
            if not storage.update(note_id, stage=stage, progress=pct):
                raise JobCancelled()

        try:
            if not storage.update(note_id, status="processing", stage="Starting", progress=1, error=None):
                return
            result = engine.transcribe(audio_path, on_progress=lambda f, s: report(2 + f * 46, s))
            segments = result["segments"]
            words = sum(len(s["text"].split()) for s in segments)
            storage.update(
                note_id,
                transcript=segments,
                duration=result["duration"],
                language=result["language"],
                word_count=words,
                search_text=exporter.build_search_text(note["title"], None, segments),
            )
            notes = engine.generate_notes(
                segments,
                context=note["context"],
                filename=note["filename"],
                on_progress=lambda f, s: report(50 + f * 48, s),
            )
            fields = dict(
                notes=notes, status="done", stage="Done", progress=100, error=None,
            )
            title = note["title"]
            if not note["title_custom"] and notes.get("title"):
                title = notes["title"][:120]
                fields["title"] = title
            fields["search_text"] = exporter.build_search_text(title, notes, segments)
            storage.update(note_id, **fields)
        except JobCancelled:
            log.info("Note %s was deleted during processing", note_id)
        except Exception as exc:
            log.exception("Processing failed for note %s", note_id)
            storage.update(note_id, status="failed", stage="Failed", error=friendly_error(exc))

    # -------------------------------------------------------------- pages
    @app.get("/")
    def index():
        return render_template(
            "index.html",
            whisper_model=engine.WHISPER_MODEL,
            notes_model=engine.NOTES_MODEL.split("/")[-1],
            allowed_exts=",".join(ALLOWED_EXTENSIONS),
            max_mb=max_mb,
        )

    @app.get("/health")
    def health():
        return jsonify(status="ok", whisper_model=engine.WHISPER_MODEL, notes_model=engine.NOTES_MODEL)

    # ---------------------------------------------------------------- API
    @app.get("/api/notes")
    def list_notes():
        notes = storage.list(request.args.get("q", ""))
        return jsonify(notes=[public(n) for n in notes])

    @app.post("/api/notes")
    def create_note():
        file = request.files.get("audio") or request.files.get("file")
        if file is None or not file.filename:
            return error("Choose an audio or video file first.")
        original = Path(file.filename).name
        ext = Path(original).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            return error(f"{ext or 'This'} files aren't supported. Upload one of: {', '.join(ALLOWED_EXTENSIONS)}.")

        note_id = uuid.uuid4().hex
        audio_name = f"{note_id}{ext}"
        path = upload_dir / audio_name
        file.save(path)
        if path.stat().st_size == 0:
            path.unlink(missing_ok=True)
            return error("That file is empty. Choose a different recording.")

        context = (request.form.get("context") or "").strip()[:1000]
        title = Path(original).stem.replace("_", " ").strip()[:120] or "Untitled meeting"
        note = storage.create(note_id, title=title, filename=original[:200], audio_name=audio_name, context=context)
        executor.submit(run_job, note_id)
        return jsonify(public(note, full=True)), 202

    @app.get("/api/notes/<note_id>")
    def get_note(note_id):
        note = storage.get(note_id, full=True)
        if note is None:
            return error("That note doesn't exist. It may have been deleted.", 404)
        return jsonify(public(note, full=True))

    @app.patch("/api/notes/<note_id>")
    def rename_note(note_id):
        title = ((request.get_json(silent=True) or {}).get("title") or "").strip()
        if not title:
            return error("Enter a title.")
        if not storage.update(note_id, title=title[:120], title_custom=1):
            return error("That note doesn't exist.", 404)
        note = storage.get(note_id, full=True)
        full_text = exporter.build_search_text(note["title"], note["notes"], note["transcript"])
        storage.update(note_id, search_text=full_text)
        return jsonify(public(note, full=True))

    @app.delete("/api/notes/<note_id>")
    def delete_note(note_id):
        existed, audio_name = storage.delete(note_id)
        if not existed:
            return error("That note doesn't exist.", 404)
        if audio_name:
            try:
                (upload_dir / audio_name).unlink(missing_ok=True)
            except OSError:  # e.g. Windows still has the file open for playback
                log.warning("Could not remove %s", audio_name)
        return jsonify(ok=True)

    @app.post("/api/notes/<note_id>/retry")
    def retry_note(note_id):
        note = storage.get(note_id)
        if note is None:
            return error("That note doesn't exist.", 404)
        if note["status"] in ("queued", "processing"):
            return error("This note is already being processed.", 409)
        if not note["audio_name"] or not (upload_dir / note["audio_name"]).exists():
            return error("The original recording is gone, so it can't be processed again. Upload it again.", 410)
        storage.update(note_id, status="queued", stage="Queued", progress=0, error=None)
        executor.submit(run_job, note_id)
        return jsonify(public(storage.get(note_id, full=True), full=True)), 202

    @app.get("/api/notes/<note_id>/audio")
    def note_audio(note_id):
        note = storage.get(note_id)
        if note is None or not note["audio_name"]:
            return error("Audio not found.", 404)
        path = upload_dir / note["audio_name"]
        if not path.exists():
            return error("Audio not found.", 404)
        mimetype = AUDIO_MIME.get(path.suffix.lower())
        return send_file(path, mimetype=mimetype, conditional=True)  # conditional = Range support

    @app.get("/api/notes/<note_id>/export")
    def export_note(note_id):
        note = storage.get(note_id, full=True)
        if note is None:
            return error("That note doesn't exist.", 404)
        fmt = request.args.get("format", "md")
        slug = exporter.slugify(note["title"])
        if fmt == "md":
            body, mimetype, ext = exporter.to_markdown(note), "text/markdown", "md"
        elif fmt == "txt":
            body, mimetype, ext = exporter.to_transcript_text(note), "text/plain", "txt"
            slug += "-transcript"
        elif fmt == "json":
            body = jsonify(public(note, full=True)).get_data(as_text=True)
            mimetype, ext = "application/json", "json"
        else:
            return error("Unknown export format. Use md, txt or json.")
        response = Response(body, mimetype=f"{mimetype}; charset=utf-8")
        if request.args.get("download"):
            response.headers["Content-Disposition"] = f'attachment; filename="{slug}.{ext}"'
        return response

    @app.errorhandler(413)
    def too_large(_exc):
        return error(f"That file is too large. The limit is {max_mb} MB.", 413)

    return app


app = create_app()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # 127.0.0.1 keeps the app private to this computer. Use HOST=0.0.0.0 inside
    # Docker, cloud IDEs and lab environments.
    app.run(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", 5000)),
        debug=False,
        threaded=True,
    )
