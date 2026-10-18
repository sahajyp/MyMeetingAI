"""Formatting helpers: timestamps, Markdown / text export, search index text."""

import re
from datetime import datetime


def fmt_ts(seconds):
    """Seconds -> 'mm:ss' or 'h:mm:ss'."""
    seconds = max(0, int(seconds or 0))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def fmt_duration(seconds):
    seconds = int(round(seconds or 0))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def slugify(text, fallback="meeting-notes"):
    slug = re.sub(r"[^A-Za-z0-9]+", "-", text or "").strip("-").lower()
    return slug[:60] or fallback


def _created(note):
    try:
        return datetime.fromisoformat(note["created_at"]).strftime("%Y-%m-%d %H:%M UTC")
    except (KeyError, ValueError, TypeError):
        return ""


def to_markdown(note):
    """Full notes document in Markdown (notes + transcript)."""
    notes = note.get("notes") or {}
    lines = [f"# {note.get('title') or 'Meeting notes'}", ""]

    meta = [m for m in (
        _created(note),
        fmt_duration(note["duration"]) if note.get("duration") else "",
        f"Source: {note['filename']}" if note.get("filename") else "",
    ) if m]
    if meta:
        lines += ["_" + " | ".join(meta) + "_", ""]

    if notes.get("overview"):
        lines += ["## Overview", "", notes["overview"], ""]
    if notes.get("key_points"):
        lines += ["## Key points", ""] + [f"- {p}" for p in notes["key_points"]] + [""]
    if notes.get("decisions"):
        lines += ["## Decisions", ""] + [f"- {d}" for d in notes["decisions"]] + [""]
    if notes.get("action_items"):
        lines += ["## Action items", ""]
        for item in notes["action_items"]:
            extras = []
            if item.get("owner"):
                extras.append(f"Owner: {item['owner']}")
            if item.get("due"):
                extras.append(f"Due: {item['due']}")
            suffix = f" ({'; '.join(extras)})" if extras else ""
            lines.append(f"- [ ] {item['task']}{suffix}")
        lines.append("")
    if notes.get("timeline"):
        lines += ["## Discussion timeline", ""]
        for part in notes["timeline"]:
            lines += [f"### {fmt_ts(part['start'])} to {fmt_ts(part['end'])}: {part['title']}", ""]
            if part.get("summary"):
                lines += [part["summary"], ""]
            lines += [f"- {p}" for p in part.get("points", [])]
            if part.get("points"):
                lines.append("")
    if notes.get("questions"):
        lines += ["## Open questions", ""] + [f"- {q}" for q in notes["questions"]] + [""]

    if note.get("transcript"):
        lines += ["## Transcript", ""]
        lines += [f"**[{fmt_ts(s['start'])}]** {s['text']}" for s in note["transcript"]]
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def to_transcript_text(note):
    header = f"{note.get('title') or 'Meeting'}\n{'=' * 40}\n"
    body = "\n".join(f"[{fmt_ts(s['start'])}] {s['text']}" for s in note.get("transcript") or [])
    return header + body + "\n"


def build_search_text(title, notes, segments):
    """Plain text used by the sidebar search box."""
    parts = [title or ""]
    if notes:
        parts += [notes.get("overview", "")]
        parts += notes.get("key_points", []) + notes.get("decisions", []) + notes.get("questions", [])
        parts += [a.get("task", "") for a in notes.get("action_items", [])]
        for part in notes.get("timeline", []):
            parts += [part.get("title", ""), part.get("summary", "")]
    parts += [s["text"] for s in segments or []]
    return "\n".join(p for p in parts if p)
