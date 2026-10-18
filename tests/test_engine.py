"""Tests for the parsing, chunking and note-merging logic (no models needed)."""

import engine
import fake_models


def seg(start, end, text):
    return {"start": start, "end": end, "text": text}


# ------------------------------------------------------------------ parsing
def test_parse_sections_plain_and_markdown_headings():
    plain = engine.parse_sections("TOPIC: Budget\nSUMMARY: Short.\nKEY POINTS:\n- a\n- b", engine.CHUNK_HEADINGS)
    assert plain["TOPIC"] == ["Budget"]
    assert plain["KEY POINTS"] == ["- a", "- b"]

    bold = engine.parse_sections("**TOPIC:** Budget\n**KEY POINTS:**\n1. a", engine.CHUNK_HEADINGS)
    assert bold["TOPIC"] == ["Budget"]
    assert bold["KEY POINTS"] == ["1. a"]


def test_bullets_strip_markers_and_none_placeholders():
    lines = ["- First point", "* Second point", "1. Third point", "- None", "N/A", "- No decisions were made."]
    assert engine.bullets(lines) == ["First point", "Second point", "Third point"]


def test_bullets_keep_real_text_that_starts_with_none_or_no():
    kept = engine.bullets(["- None of the vendors met the deadline, so the contract is on hold"])
    assert kept == ["None of the vendors met the deadline, so the contract is on hold"]


def test_parse_action_extracts_owner_and_due():
    item = engine.parse_action("Send the report (Owner: Priya; Due: Friday)")
    assert item == {"task": "Send the report", "owner": "Priya", "due": "Friday"}


def test_parse_action_treats_unassigned_and_unspecified_as_empty():
    item = engine.parse_action("Pick a venue (Owner: Unassigned; Due: Not specified)")
    assert item == {"task": "Pick a venue", "owner": "", "due": ""}


def test_parse_action_without_pattern_keeps_the_text():
    assert engine.parse_action("Follow up with legal") == {"task": "Follow up with legal", "owner": "", "due": ""}


def test_dedupe_removes_near_duplicates():
    items = ["Launch moves to December 2nd.", "Launch moves to December 2nd", "Hire a designer"]
    assert engine.dedupe(items) == ["Launch moves to December 2nd.", "Hire a designer"]


# ----------------------------------------------------------------- chunking
def test_chunk_segments_respects_size_and_order():
    segments = [seg(i, i + 1, "x" * 100) for i in range(10)]
    chunks = engine.chunk_segments(segments, chunk_chars=350)
    assert [len(c) for c in chunks] == [3, 3, 3, 1]
    assert [s for c in chunks for s in c] == segments


def test_chunk_segments_grows_chunks_for_very_long_meetings():
    # About 150k characters (a ~2.5 hour meeting): chunks grow so the call count stays bounded.
    segments = [seg(i, i + 1, "x" * 500) for i in range(300)]
    chunks = engine.chunk_segments(segments, chunk_chars=3200)
    assert len(chunks) <= engine.MAX_CHUNKS + 1

    # Even longer: chunk size is capped, so call count may exceed the target but chunks stay small enough.
    huge = [seg(i, i + 1, "x" * 500) for i in range(400)]
    chunks = engine.chunk_segments(huge, chunk_chars=3200)
    assert max(sum(len(s["text"]) for s in c) for c in chunks) <= engine.MAX_CHUNK_CHARS + 500


# ------------------------------------------------------------- generate_notes
def test_generate_notes_merges_chunks(monkeypatch):
    fake_models.install(setter=lambda o, n, v: monkeypatch.setattr(o, n, v))
    segments, _ = fake_models.scripted_segments()
    segments = [seg(s.start, s.end, s.text.strip()) for s in segments]
    calls = []

    notes = engine.generate_notes(segments, filename="atlas.wav", on_progress=lambda f, s: calls.append((f, s)))

    count = len(engine.chunk_segments(segments))
    assert count == 3                                  # one canned reply per chunk
    assert len(notes["key_points"]) <= 2 * count       # top-level list stays short
    assert notes["title"].startswith("Atlas Launch Sync")
    assert len(notes["timeline"]) == count
    assert notes["timeline"][0]["title"] == "Launch date and engineering status"
    assert notes["timeline"][1]["title"] == "Onboarding redesign"
    assert any("November 18th" in d for d in notes["decisions"])
    owners = {a["owner"] for a in notes["action_items"]}
    assert {"Priya", "Marcus", "Elena", "Dev"} <= owners
    assert any(a["owner"] == "" for a in notes["action_items"])  # "Unassigned" cleaned
    assert len(notes["questions"]) == 3
    assert notes["key_points"] and all(isinstance(p, str) for p in notes["key_points"])
    fractions = [f for f, _ in calls]
    assert fractions == sorted(fractions) and fractions[-1] == 1.0
    assert any("part 2 of" in stage for _, stage in calls)


def test_generate_notes_single_chunk_has_no_timeline(monkeypatch):
    fake_models.install(setter=lambda o, n, v: monkeypatch.setattr(o, n, v), chunk_chars=100000)
    segments = [seg(0, 5, "We agreed to ship on Friday."), seg(5, 9, "Priya owns the release notes.")]
    notes = engine.generate_notes(segments)
    assert notes["timeline"] == []
    assert len(notes["key_points"]) == 4


def test_generate_notes_survives_unformatted_model_output(monkeypatch):
    monkeypatch.setattr(engine, "_chat", lambda system, user, max_new_tokens=400: "Sure! Here is what happened in the meeting.")
    segments = [seg(0, 5, "We talked about the roadmap for next quarter.")]
    notes = engine.generate_notes(segments, filename="roadmap_review.mp3")
    assert notes["title"] == "roadmap review"          # falls back to the file name
    assert notes["overview"]                            # never empty
    assert notes["decisions"] == [] and notes["action_items"] == []


def test_context_is_passed_to_the_model(monkeypatch):
    seen = []
    monkeypatch.setattr(engine, "_chat", lambda system, user, max_new_tokens=400: seen.append(user) or "TOPIC: x\nSUMMARY: y")
    engine.generate_notes([seg(0, 5, "Hello team, welcome to the standup.")], context="Platform team standup")
    assert all("Platform team standup" in prompt for prompt in seen)


# --------------------------------------------------------------- transcribe
def test_transcribe_collects_segments_and_progress(monkeypatch):
    fake_models.install(setter=lambda o, n, v: monkeypatch.setattr(o, n, v))
    calls = []
    result = engine.transcribe("ignored.wav", on_progress=lambda f, s: calls.append(f))
    assert result["language"] == "en"
    assert result["segments"][0]["text"].startswith("Okay, let's get started")
    assert result["duration"] > 60
    assert calls == sorted(calls) and calls[-1] <= 1.0


def test_transcribe_raises_when_nothing_was_said(monkeypatch):
    monkeypatch.setattr(engine, "_get_whisper", lambda force_cpu=False: fake_models.FakeWhisper(segments=[]))
    try:
        engine.transcribe("silent.wav")
    except engine.NoSpeechError as exc:
        assert "No speech" in str(exc)
    else:
        raise AssertionError("NoSpeechError was not raised")
