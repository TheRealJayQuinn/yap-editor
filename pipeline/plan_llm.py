#!/usr/bin/env python3
"""Draft a *structural* cuts.json from word timestamps with an LLM.

`plan.py` performs the two mechanical passes — flub removal and the silence
pass — and says plainly that best-take selection, tangent trims, and hook
surgery are "the human's job". This script does that judgement layer instead,
by handing the transcript to Perplexity's chat API (https://api.perplexity.ai)
and asking for a reordered, reasoned cut.

It is not a replacement for a human editor; it is the same draft `plan.py`
writes, one rung further up. Every segment the model returns is snapped back to
a real word boundary from the transcript, so the model chooses *what* and *in
what order*, never the exact frames — the timestamps stay the authority for the
cut, exactly as the rest of the pipeline assumes.

    export PERPLEXITY_API_KEY=pplx-...
    python3 pipeline/plan_llm.py build/sample/A.words.json \
        -o build/sample/cuts.draft.json --media sample/sample-16x9.mp4 \
        --focus "why editing takes longer than filming"

Use `--dry-run` to print the exact request without a key or a network call.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from common import (
    load_json,
    repo_path,
    safe_record_path,
    write_json,
)
from perplexity import (
    DEFAULT_API_KEY_ENV,
    DEFAULT_BASE_URL,
    PerplexityError,
    api_key as read_api_key,
    chat,
    extract_json_object,
)


DEFAULT_MODEL = "sonar-pro"

SENTENCE_END = re.compile(r"[.!?][\"')\]]*$")

SYSTEM_PROMPT = """\
You are a reel editor doing yap post-production: you take one raw talking-to-camera \
take and find the video inside the footage. You return the structural cut plan only.

The method, non-negotiable:
- One focus. Every kept second serves the single take, story, or epiphany.
- The first seconds are the video. Open on the question or the strongest take, never \
on wind-up. If the hook was recorded later in the take, move it to the front.
- Cut resistance: silences, filler ("um", "so, today I wanted to talk about..."), \
flubs and restarts (keep the last, cleanest attempt), and tangents that serve a \
different focus.
- Progression is retention; pay off fast, then stop. Do not pad for length and never \
cut the conflict or the payoff to save time.
- Every segment you keep is a claim about the video, so every one carries a one-line \
reason tied to the focus.

You are given the transcript as numbered sentences, each with its source start and end \
time in seconds. You choose which spans to keep and the ORDER they play in — the array \
order is the order of the final cut, which is why moving the hook to 0:00 is expressed \
by putting it first, not by sorting.

Return ONLY a JSON object, no prose, no markdown fences, in exactly this shape:

{
  "headline": "the one line that stays on screen above the clip",
  "focus": "the single focus you cut toward, one clause",
  "segments": [
    {
      "start": <seconds into the source take>,
      "end": <seconds into the source take>,
      "beat": "hook | build | conflict | payoff | cta | close",
      "reason": "one line, tied to the focus"
    }
  ]
}

Rules for the numbers:
- start and end are seconds in the SOURCE take (use the times shown against the \
sentences), not positions in the final cut.
- end must be greater than start. Keep spans on sentence boundaries where you can; \
they will be snapped to the nearest real word boundary regardless.
- Order the segments the way the finished reel should play.
- Keep it tight. Prefer the fewest segments that deliver the focus with a clean \
hook and a fast payoff.\
"""


def sentence_lines(words: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Group words into sentences with a start, an end, and the joined text."""
    lines: List[Dict[str, Any]] = []
    current: List[Dict[str, Any]] = []
    for item in words:
        current.append(item)
        if SENTENCE_END.search(str(item.get("word", ""))):
            built = _line(current)
            if built:
                lines.append(built)
            current = []
    if current:
        built = _line(current)
        if built:
            lines.append(built)
    return lines


def _line(group: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    text = " ".join(str(item.get("word", "")).strip() for item in group).strip()
    text = re.sub(r"\s+", " ", text)
    if not text:
        return None
    try:
        start = round(float(group[0]["start"]), 3)
        end = round(float(group[-1]["end"]), 3)
    except (KeyError, TypeError, ValueError):
        return None
    return {"start": start, "end": end, "text": text}


def transcript_block(lines: Sequence[Dict[str, Any]]) -> str:
    rows = []
    for index, line in enumerate(lines, start=1):
        rows.append(f"[{index:02d}] ({line['start']:.2f}–{line['end']:.2f}) {line['text']}")
    return "\n".join(rows)


def build_messages(
    lines: Sequence[Dict[str, Any]],
    *,
    focus: Optional[str],
    target_length: Optional[float],
    total_duration: Optional[float],
) -> List[Dict[str, str]]:
    parts: List[str] = []
    if focus:
        parts.append(f"Focus (given): {focus}")
    else:
        parts.append("Focus: infer the single focus from the transcript and name it.")
    if total_duration:
        parts.append(f"Raw take length: {total_duration:.2f}s.")
    if target_length:
        parts.append(f"Target finished length: about {target_length:.0f}s. Do not pad to reach it.")
    parts.append("")
    parts.append("Transcript (numbered sentences, source times in seconds):")
    parts.append(transcript_block(lines))
    parts.append("")
    parts.append("Return the JSON cut plan now.")
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(parts)},
    ]


def nearest(value: float, boundaries: Sequence[float]) -> float:
    return min(boundaries, key=lambda boundary: abs(boundary - value))


def resolve_segments(
    raw_segments: Sequence[Any],
    words: Sequence[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Snap model spans to real word boundaries; drop or downgrade the invalid."""
    starts = sorted({round(float(word["start"]), 3) for word in words})
    ends = sorted({round(float(word["end"]), 3) for word in words})
    floor, ceil = starts[0], ends[-1]
    notes: List[str] = []
    resolved: List[Dict[str, Any]] = []

    for position, entry in enumerate(raw_segments, start=1):
        if not isinstance(entry, dict):
            notes.append(f"segment {position}: not an object, skipped")
            continue
        try:
            want_start = float(entry["start"])
            want_end = float(entry["end"])
        except (KeyError, TypeError, ValueError):
            notes.append(f"segment {position}: missing or non-numeric start/end, skipped")
            continue
        start = nearest(max(floor, min(want_start, ceil)), starts)
        end = nearest(max(floor, min(want_end, ceil)), ends)
        if end <= start:
            notes.append(f"segment {position}: start {want_start:.2f}s not before end {want_end:.2f}s, skipped")
            continue
        reason = str(entry.get("reason", "")).strip()
        kind = "structural"
        if not reason:
            kind = "mechanical"
            notes.append(f"segment {position}: no reason given, downgraded to mechanical")
        segment: Dict[str, Any] = {
            "take": "A",
            "start": round(start, 3),
            "end": round(end, 3),
            "beat": str(entry.get("beat", f"segment-{position:03d}")).strip() or f"segment-{position:03d}",
            "kind": kind,
        }
        if kind == "structural":
            segment["reason"] = reason
        resolved.append(segment)

    return resolved, notes


def choose_slug(words_path: Path, media: Optional[Path], supplied: Optional[str]) -> str:
    if supplied:
        return supplied
    source = media or words_path
    name = source.stem
    if name.endswith(".words"):
        name = name[:-6]
    slug = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")
    return slug or "draft"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("words", type=Path)
    parser.add_argument("-o", "--output", required=True, type=Path)
    parser.add_argument("--media", type=Path)
    parser.add_argument("--slug")
    parser.add_argument("--headline", help="override the headline the model proposes")
    parser.add_argument("--focus", help="the single focus to cut toward; inferred if omitted")
    parser.add_argument("--target-length", type=float, help="target finished length in seconds (a hint, not a cap)")
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Perplexity model (default: {DEFAULT_MODEL})")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--api-key-env", default=DEFAULT_API_KEY_ENV, help="env var holding the API key")
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--max-tokens", type=int, default=2000)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--dry-run", action="store_true", help="print the request and exit without calling the API")
    parser.add_argument("--print-response", action="store_true", help="print the raw model response before parsing")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    words_path = repo_path(str(args.words))
    output = repo_path(str(args.output))
    media = repo_path(str(args.media)) if args.media else None

    try:
        data = load_json(words_path)
    except (OSError, ValueError) as exc:
        print(f"ERROR: could not read words JSON: {exc}", file=sys.stderr)
        return 1
    words = data.get("words") if isinstance(data, dict) else None
    if not isinstance(words, list) or not words:
        print("ERROR: words JSON contains no word timestamps", file=sys.stderr)
        return 1
    if media and not media.exists():
        print(f"ERROR: media file not found: {args.media}", file=sys.stderr)
        return 1

    lines = sentence_lines(words)
    if not lines:
        print("ERROR: could not group the transcript into sentences", file=sys.stderr)
        return 1

    total_duration = data.get("duration") if isinstance(data, dict) else None
    try:
        total_duration = float(total_duration) if total_duration is not None else None
    except (TypeError, ValueError):
        total_duration = None

    messages = build_messages(
        lines,
        focus=args.focus,
        target_length=args.target_length,
        total_duration=total_duration,
    )

    if args.dry_run:
        print(f"POST {args.base_url.rstrip('/')}/chat/completions")
        print(f"model: {args.model}  temperature: {args.temperature}  max_tokens: {args.max_tokens}")
        print("--- system ---")
        print(messages[0]["content"])
        print("--- user ---")
        print(messages[1]["content"])
        return 0

    try:
        key = read_api_key(args.api_key_env)
    except PerplexityError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    try:
        content, _ = chat(
            messages,
            api_key=key,
            base_url=args.base_url,
            model=args.model,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            timeout=args.timeout,
        )
    except PerplexityError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.print_response:
        print("--- model response ---", file=sys.stderr)
        print(content, file=sys.stderr)
        print("--- end response ---", file=sys.stderr)

    try:
        parsed = extract_json_object(content)
    except PerplexityError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    raw_segments = parsed.get("segments")
    if not isinstance(raw_segments, list) or not raw_segments:
        print("ERROR: model returned no segments", file=sys.stderr)
        return 1

    segments, notes = resolve_segments(raw_segments, words)
    if not segments:
        print("ERROR: no valid segments survived boundary snapping", file=sys.stderr)
        for note in notes:
            print(f"  {note}", file=sys.stderr)
        return 1

    slug = choose_slug(words_path, media, args.slug)
    if not re.fullmatch(r"[a-z0-9-]+", slug):
        print("ERROR: slug must match [a-z0-9-]+", file=sys.stderr)
        return 1

    headline = args.headline if args.headline is not None else str(parsed.get("headline", "")).strip()

    source = data.get("source", safe_record_path(media or words_path)) if isinstance(data, dict) else None
    media_value = safe_record_path(media) if media else (source or safe_record_path(words_path))
    output_payload = {
        "version": 1,
        "slug": slug,
        "fps": args.fps,
        "headline": headline,
        "pad": [0.07, 0.07],
        "loudness": {"i": -14, "tp": -1.5, "lra": 11},
        "takes": {"A": {"path": media_value, "words": safe_record_path(words_path)}},
        "segments": segments,
    }
    write_json(output, output_payload)

    structural = sum(1 for segment in segments if segment.get("kind") == "structural")
    mechanical = len(segments) - structural
    print(f"Wrote LLM draft {safe_record_path(output)} with {len(segments)} segment(s): {structural} structural, {mechanical} mechanical")
    focus = str(parsed.get("focus", "")).strip()
    if focus:
        print(f"Focus (per model): {focus}")
    if headline:
        print(f"Headline (per model): {headline}")
    for note in notes:
        print(f"  note: {note}")
    print("This is a draft. Read every reason against the focus before you ship it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
