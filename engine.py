"""AI engine: speech-to-text (faster-whisper) and structured meeting notes (instruct LLM).

Heavy libraries (faster-whisper, torch, transformers) are imported lazily the first
time they are needed, so importing this module is instant and the parsing /
chunking logic can be tested without any model installed.

Pipeline
    audio -> Whisper -> timestamped segments
          -> split into chunks -> LLM writes notes for each chunk
          -> LLM writes a title + overview from the chunk notes
          -> merged into one structured document
"""

import difflib
import logging
import math
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

from exporter import fmt_ts

log = logging.getLogger("mymeeting.engine")

# --------------------------------------------------------------------------
# Configuration (all overridable with environment variables)
# --------------------------------------------------------------------------
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "base")          # tiny, base, small, medium, large-v3
WHISPER_DEVICE = os.environ.get("WHISPER_DEVICE", "auto").lower()  # auto, cpu, cuda
WHISPER_LANGUAGE = os.environ.get("WHISPER_LANGUAGE") or None    # e.g. "en"; default: auto-detect
NOTES_MODEL = os.environ.get("NOTES_MODEL", "Qwen/Qwen2.5-1.5B-Instruct")
CPU_THREADS = int(os.environ.get("CPU_THREADS", "0"))            # 0 = library default

CHUNK_CHARS = int(os.environ.get("CHUNK_CHARS", "3200"))   # transcript characters per LLM call
MAX_CHUNKS = 24                                            # long meetings get bigger chunks instead
MAX_CHUNK_CHARS = 8000
CHUNK_TOKENS = 450                                         # max generated tokens per chunk
FINAL_TOKENS = 320

SYSTEM_PROMPT = (
    "You are an expert meeting note-taker. You write accurate, specific, well-organized "
    "notes using only what is said in the transcript. You never invent names, numbers, "
    "dates or decisions."
)


class NoSpeechError(RuntimeError):
    """Raised when a recording contains no recognizable speech."""


# --------------------------------------------------------------------------
# Speech-to-text
# --------------------------------------------------------------------------
_whisper = None
_whisper_device = None
_whisper_lock = threading.Lock()


def _detect_whisper_device():
    if WHISPER_DEVICE in ("cpu", "cuda"):
        return WHISPER_DEVICE
    try:
        import ctranslate2
        return "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
    except Exception:
        return "cpu"


def _get_whisper(force_cpu=False):
    """Load the Whisper model once and reuse it."""
    global _whisper, _whisper_device
    with _whisper_lock:
        if _whisper is not None and not (force_cpu and _whisper_device != "cpu"):
            return _whisper
        from faster_whisper import WhisperModel

        device = "cpu" if force_cpu else _detect_whisper_device()
        compute_type = "float16" if device == "cuda" else "int8"
        log.info("Loading Whisper '%s' on %s (%s)", WHISPER_MODEL, device, compute_type)
        _whisper = WhisperModel(
            WHISPER_MODEL, device=device, compute_type=compute_type, cpu_threads=CPU_THREADS
        )
        _whisper_device = device
        return _whisper


def transcribe(path, on_progress=None):
    """Transcribe an audio/video file.

    Returns {"segments": [{"start", "end", "text"}], "duration": float, "language": str}.
    on_progress(fraction 0..1, stage_text) is called as segments are produced.
    """
    progress = on_progress or (lambda fraction, stage: None)
    progress(0.0, "Loading speech model")

    def run(model):
        progress(0.03, "Transcribing audio")
        segments_iter, info = model.transcribe(
            str(path),
            beam_size=5,
            vad_filter=True,                    # skip silence, fewer hallucinations
            condition_on_previous_text=False,   # avoids repeated-phrase loops
            language=WHISPER_LANGUAGE,
        )
        duration = float(getattr(info, "duration", 0) or 0)
        segments = []
        for seg in segments_iter:
            text = (seg.text or "").strip()
            if text:
                segments.append(
                    {"start": round(float(seg.start), 2), "end": round(float(seg.end), 2), "text": text}
                )
            if duration:
                progress(min(float(seg.end) / duration, 1.0), "Transcribing audio")
        return segments, duration, getattr(info, "language", None)

    try:
        segments, duration, language = run(_get_whisper())
    except Exception:
        # A GPU that is present but unusable (missing CUDA libraries) should not break the app.
        if _whisper_device == "cuda":
            log.warning("GPU transcription failed; retrying on CPU", exc_info=True)
            segments, duration, language = run(_get_whisper(force_cpu=True))
        else:
            raise

    if not segments or sum(len(s["text"]) for s in segments) < 12:
        raise NoSpeechError(
            "No speech was detected in this recording. Check that the file has audible "
            "speech and try again."
        )
    if not duration:
        duration = segments[-1]["end"]
    return {"segments": segments, "duration": duration, "language": language}


# --------------------------------------------------------------------------
# Language model
# --------------------------------------------------------------------------
_llm = None            # (tokenizer, model, device)
_llm_lock = threading.Lock()
_generate_lock = threading.Lock()


def _llm_ready():
    return _llm is not None


def _get_llm():
    global _llm
    with _llm_lock:
        if _llm is None:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer

            device = "cuda" if torch.cuda.is_available() else "cpu"
            dtype = torch.float16 if device == "cuda" else torch.float32
            log.info("Loading %s on %s", NOTES_MODEL, device)
            tokenizer = AutoTokenizer.from_pretrained(NOTES_MODEL)
            try:
                model = AutoModelForCausalLM.from_pretrained(NOTES_MODEL, dtype=dtype, low_cpu_mem_usage=True)
            except (TypeError, ValueError):  # older transformers releases call it torch_dtype
                model = AutoModelForCausalLM.from_pretrained(
                    NOTES_MODEL, torch_dtype=dtype, low_cpu_mem_usage=True
                )
            model.to(device)
            model.eval()
            _llm = (tokenizer, model, device)
        return _llm


def _chat(system, user, max_new_tokens=400):
    """Run one chat turn through the LLM and return the reply text."""
    import torch

    tokenizer, model, device = _get_llm()
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(text, return_tensors="pt").to(device)
    with _generate_lock, torch.inference_mode():
        output = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,            # deterministic output suits note-taking
            temperature=None,
            top_p=None,
            top_k=None,
            repetition_penalty=1.05,
            pad_token_id=tokenizer.eos_token_id,
        )
    return tokenizer.decode(output[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True).strip()


# --------------------------------------------------------------------------
# Prompts
# --------------------------------------------------------------------------
def _context_block(context):
    if not context:
        return ""
    return (
        "Background from the user (use it to interpret names, projects and jargon):\n"
        f"{context}\n\n"
    )


def chunk_prompt(text, start, end, context=""):
    return (
        f"{_context_block(context)}"
        f"Transcript excerpt from a meeting ({fmt_ts(start)} to {fmt_ts(end)}):\n"
        f'"""\n{text}\n"""\n\n'
        "Write notes for this excerpt in EXACTLY this format (keep the labels in English; "
        "write the content in the same language as the transcript):\n\n"
        "TOPIC: <short title, at most 8 words>\n"
        "SUMMARY: <2-3 sentences describing what was discussed>\n"
        "KEY POINTS:\n"
        "- <specific point with concrete details such as names, numbers and dates>\n"
        "- <another point>\n"
        "DECISIONS:\n"
        "- <something the group decided or agreed on>\n"
        "ACTION ITEMS:\n"
        "- <task> (Owner: <person or Unassigned>; Due: <date or Not specified>)\n"
        "QUESTIONS:\n"
        "- <open question or unresolved issue>\n\n"
        "Rules:\n"
        "- Use only information from the excerpt. Do not invent names, numbers or decisions.\n"
        "- Give 3 to 6 key points.\n"
        '- If a section has nothing to report, write "- None" under it.'
    )


def overview_prompt(sections, context=""):
    parts = "\n".join(
        f"{i}. [{fmt_ts(s['start'])}] {s['topic']}: {s['summary']}" for i, s in enumerate(sections, 1)
    )
    return (
        f"{_context_block(context)}"
        f"Below are notes for each part of a meeting, in order:\n\n{parts}\n\n"
        "Write a title and an overview of the whole meeting using EXACTLY this format:\n\n"
        "TITLE: <clear, specific meeting title, at most 10 words>\n"
        "OVERVIEW: <3-5 sentence executive summary covering the purpose, main topics, "
        "outcomes and next steps>\n\n"
        "Use only information from the notes above."
    )


# --------------------------------------------------------------------------
# Parsing the model's text output
# --------------------------------------------------------------------------
CHUNK_HEADINGS = ("TOPIC", "SUMMARY", "KEY POINTS", "DECISIONS", "ACTION ITEMS", "QUESTIONS")
_NONE_PHRASES = {
    "none", "na", "nil", "nothing", "none mentioned", "none identified", "none discussed",
    "no decisions", "no decisions were made", "no action items", "no questions",
    "no open questions", "not applicable", "not specified",
}
_BULLET = re.compile(r"^\s*(?:[-*•–]+|\d+[.)])\s*")
_ACTION = re.compile(
    r"^(?P<task>.*?)\s*\(\s*(?:Owner|Assignee)\s*:\s*(?P<owner>[^;)]*?)\s*"
    r"(?:[;,]\s*(?:Due|Deadline)\s*:\s*(?P<due>[^)]*?))?\s*\)\s*\.?\s*$",
    re.I,
)
_EMPTY_VALUES = {"", "unassigned", "not specified", "none", "n/a", "na", "unknown", "tbd"}


def parse_sections(text, headings):
    """Split 'LABEL: text' style output into {LABEL: [lines]}."""
    pattern = re.compile(
        r"^\s*[#*\s]*(" + "|".join(re.escape(h) for h in headings) + r")\b[\s*]*:[\s*]*(.*)$",
        re.I,
    )
    sections, current = {}, None
    for line in (text or "").splitlines():
        match = pattern.match(line)
        if match:
            current = match.group(1).upper()
            sections[current] = []
            rest = match.group(2).strip()
            if rest:
                sections[current].append(rest)
        elif current and line.strip():
            sections[current].append(line.strip())
    return sections


def _clean_inline(text):
    text = re.sub(r"\s+", " ", text or "").strip()
    text = re.sub(r"^\*+|\*+$", "", text).strip()
    return text.strip("\"' ").strip()


def _is_none(text):
    normalized = re.sub(r"[^a-z ]", "", text.lower()).strip()
    return normalized in _NONE_PHRASES or (normalized.startswith("none ") and len(normalized) < 40)


def bullets(lines):
    """Turn raw lines into clean bullet strings, dropping 'None' placeholders."""
    out = []
    for line in lines or []:
        item = _clean_inline(_BULLET.sub("", line))
        if item and not _is_none(item):
            out.append(item)
    return out


def parse_action(text):
    match = _ACTION.match(text)
    if not match:
        return {"task": text, "owner": "", "due": ""}

    def value(raw):
        raw = (raw or "").strip()
        return "" if raw.lower() in _EMPTY_VALUES else raw

    task = match.group("task").strip() or text
    return {"task": task, "owner": value(match.group("owner")), "due": value(match.group("due"))}


def dedupe(items, key=lambda x: x, threshold=0.88):
    """Drop near-duplicates (the same point often appears in two chunks)."""
    kept = []
    for item in items:
        text = re.sub(r"\W+", " ", key(item).lower()).strip()
        if not text:
            continue
        if any(difflib.SequenceMatcher(None, text, k).ratio() >= threshold for k, _ in kept):
            continue
        kept.append((text, item))
    return [item for _, item in kept]


def parse_chunk(raw, fallback_text="", index=0):
    """Parse one chunk's LLM output into a dict, with fallbacks for malformed replies."""
    sections = parse_sections(raw, CHUNK_HEADINGS)
    topic = _clean_inline(" ".join(sections.get("TOPIC", [])))
    summary = _clean_inline(" ".join(sections.get("SUMMARY", [])))
    if not summary:
        # The model ignored the format: use whatever it wrote, or the transcript itself.
        summary = _clean_inline(raw)[:500] or _clean_inline(fallback_text)[:400]
    return {
        "topic": topic[:100] or f"Part {index + 1}",
        "summary": summary,
        "points": bullets(sections.get("KEY POINTS")),
        "decisions": bullets(sections.get("DECISIONS")),
        "actions": [parse_action(a) for a in bullets(sections.get("ACTION ITEMS"))],
        "questions": bullets(sections.get("QUESTIONS")),
    }


# --------------------------------------------------------------------------
# Notes generation
# --------------------------------------------------------------------------
def chunk_segments(segments, chunk_chars=None):
    """Group consecutive segments into chunks of roughly chunk_chars characters."""
    chunk_chars = chunk_chars or CHUNK_CHARS
    total = sum(len(s["text"]) + 1 for s in segments)
    target = chunk_chars
    if total / max(chunk_chars, 1) > MAX_CHUNKS:  # very long meeting: fewer, larger chunks
        target = min(max(chunk_chars, math.ceil(total / MAX_CHUNKS)), MAX_CHUNK_CHARS)
    chunks, current, size = [], [], 0
    for seg in segments:
        length = len(seg["text"]) + 1
        if current and size + length > target:
            chunks.append(current)
            current, size = [], 0
        current.append(seg)
        size += length
    if current:
        chunks.append(current)
    return chunks


def _clean_title(text):
    title = _clean_inline(text).rstrip(".")
    return title[:100]


def generate_notes(segments, context="", filename="", on_progress=None):
    """Turn transcript segments into a structured notes dict."""
    progress = on_progress or (lambda fraction, stage: None)
    chunks = chunk_segments(segments)
    count = len(chunks)
    steps = count + 1  # one call per chunk plus the final overview

    if not _llm_ready():
        progress(0.0, "Loading language model")

    sections = []
    for i, chunk in enumerate(chunks):
        progress(i / steps, f"Writing notes (part {i + 1} of {count})" if count > 1 else "Writing notes")
        start, end = chunk[0]["start"], chunk[-1]["end"]
        text = " ".join(s["text"] for s in chunk)
        raw = _chat(SYSTEM_PROMPT, chunk_prompt(text, start, end, context), max_new_tokens=CHUNK_TOKENS)
        parsed = parse_chunk(raw, fallback_text=text, index=i)
        parsed.update(start=start, end=end)
        sections.append(parsed)

    progress(count / steps, "Writing the overview")
    final_raw = _chat(SYSTEM_PROMPT, overview_prompt(sections, context), max_new_tokens=FINAL_TOKENS)
    head = parse_sections(final_raw, ("TITLE", "OVERVIEW"))

    stem = Path(filename).stem.replace("_", " ").strip() if filename else ""
    title = _clean_title(" ".join(head.get("TITLE", []))) or stem or "Meeting notes"
    overview = _clean_inline(" ".join(head.get("OVERVIEW", [])))
    if not overview:
        overview = " ".join(s["summary"] for s in sections)[:900]

    decisions = dedupe(d for s in sections for d in s["decisions"])
    questions = dedupe(q for s in sections for q in s["questions"])
    actions = dedupe((a for s in sections for a in s["actions"]), key=lambda a: a["task"])

    if count == 1:
        key_points, timeline = sections[0]["points"], []
    else:
        # The timeline cards already list every point, so keep the top-level list short.
        key_points = dedupe(p for s in sections for p in s["points"][:2])[:12]
        timeline = [
            {
                "start": s["start"],
                "end": s["end"],
                "title": s["topic"],
                "summary": s["summary"],
                "points": s["points"],
            }
            for s in sections
        ]

    progress(1.0, "Finalizing")
    return {
        "title": title,
        "overview": overview,
        "key_points": key_points,
        "decisions": decisions,
        "action_items": actions,
        "questions": questions,
        "timeline": timeline,
        "model": NOTES_MODEL,
        "whisper_model": WHISPER_MODEL,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
