#!/usr/bin/env python3
"""Research a topic and draft scroll-stopping hooks — before you film.

This is the pre-shoot end of the pipeline. `plan_llm.py` cuts footage you
already have; this decides what is worth pointing a camera at. It asks
Perplexity — whose models search the live web — to research a topic and hand
back a tight brief: the angle worth taking, a handful of hooks written to stop
the scroll, the load-bearing facts, and the sources behind them.

    export PERPLEXITY_API_KEY=pplx-...
    python3 pipeline/research.py "testosterone and sleep after 40" \
        --platform reels --hooks 6

The hooks are raw material for a take, not a script. Say them in your own voice;
verify any claim against the sources before you put a number on camera.

Use `--dry-run` to print the request without a key or a network call.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any, Dict, List, Optional, Sequence

from common import repo_path, write_json
from perplexity import (
    DEFAULT_API_KEY_ENV,
    DEFAULT_BASE_URL,
    PerplexityError,
    api_key as read_api_key,
    chat,
    extract_json_object,
)


DEFAULT_MODEL = "sonar-pro"

SYSTEM_PROMPT = """\
You research a topic for a short talking-to-camera video and return hooks that stop \
the scroll. You have live web access; use it, and ground the specifics in what you \
find rather than inventing them.

What makes a hook work:
- It opens on tension, a question, or a claim that contradicts what the viewer \
assumes — never on wind-up, never on "in this video".
- It is one spoken line. Short enough to say in a breath, concrete enough to make \
someone stop.
- It promises the one payoff the video delivers; it does not bait something the \
video can't pay off.
- No hashtags, no emoji, no "let's dive in". Plain spoken language.

Return ONLY a JSON object, no prose, no markdown fences, in exactly this shape:

{
  "topic": "the topic, restated in one clause",
  "angle": "the single sharpest angle to take on it, one sentence",
  "hooks": ["one spoken hook line", "another", "..."],
  "facts": [
    {"claim": "a specific, load-bearing fact stated plainly", "source": "where it came from"}
  ],
  "avoid": ["a tired or misleading framing to steer clear of", "..."]
}

Every fact must be one you can point to a source for. If the evidence is thin or \
contested, say so in the claim rather than overstating it.\
"""


def build_messages(
    topic: str,
    *,
    platform: Optional[str],
    angle: Optional[str],
    audience: Optional[str],
    hooks: int,
) -> List[Dict[str, str]]:
    parts: List[str] = [f"Topic: {topic}"]
    if angle:
        parts.append(f"Angle to lean into: {angle}")
    if audience:
        parts.append(f"Audience: {audience}")
    if platform:
        parts.append(f"Platform: {platform}. Write hooks that fit how people watch there.")
    parts.append(f"Give {hooks} hooks, ranked strongest first.")
    parts.append("Research the topic on the live web, then return the JSON brief now.")
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(parts)},
    ]


def as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def render_brief(brief: Dict[str, Any], citations: Sequence[str]) -> str:
    lines: List[str] = []
    topic = str(brief.get("topic", "")).strip()
    angle = str(brief.get("angle", "")).strip()
    if topic:
        lines.append(f"TOPIC  {topic}")
    if angle:
        lines.append(f"ANGLE  {angle}")

    hooks = [str(hook).strip() for hook in as_list(brief.get("hooks")) if str(hook).strip()]
    if hooks:
        lines.append("")
        lines.append("HOOKS")
        for index, hook in enumerate(hooks, start=1):
            lines.append(f"  {index}. {hook}")

    facts = [fact for fact in as_list(brief.get("facts")) if isinstance(fact, dict)]
    if facts:
        lines.append("")
        lines.append("FACTS")
        for fact in facts:
            claim = str(fact.get("claim", "")).strip()
            source = str(fact.get("source", "")).strip()
            if not claim:
                continue
            lines.append(f"  - {claim}" + (f"  [{source}]" if source else ""))

    avoid = [str(item).strip() for item in as_list(brief.get("avoid")) if str(item).strip()]
    if avoid:
        lines.append("")
        lines.append("AVOID")
        for item in avoid:
            lines.append(f"  - {item}")

    if citations:
        lines.append("")
        lines.append("SOURCES")
        for index, url in enumerate(citations, start=1):
            lines.append(f"  [{index}] {url}")

    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("topic", help="what the video is about")
    parser.add_argument("--platform", help="reels | shorts | tiktok | x | linkedin (a hint on format)")
    parser.add_argument("--angle", help="an angle to lean into; the model picks one if omitted")
    parser.add_argument("--audience", help="who the video is for")
    parser.add_argument("--hooks", type=int, default=6, help="how many hooks to draft (default: 6)")
    parser.add_argument("-o", "--output", help="also write the JSON brief to this path")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Perplexity model (default: {DEFAULT_MODEL})")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--api-key-env", default=DEFAULT_API_KEY_ENV, help="env var holding the API key")
    parser.add_argument("--temperature", type=float, default=0.4)
    parser.add_argument("--max-tokens", type=int, default=1500)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--json", action="store_true", help="print the raw JSON brief instead of the formatted view")
    parser.add_argument("--dry-run", action="store_true", help="print the request and exit without calling the API")
    parser.add_argument("--print-response", action="store_true", help="print the raw model response before parsing")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    topic = args.topic.strip()
    if not topic:
        print("ERROR: topic is empty", file=sys.stderr)
        return 1
    if args.hooks < 1:
        print("ERROR: --hooks must be at least 1", file=sys.stderr)
        return 1

    messages = build_messages(
        topic,
        platform=args.platform,
        angle=args.angle,
        audience=args.audience,
        hooks=args.hooks,
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
        content, citations = chat(
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
        brief = extract_json_object(content)
    except PerplexityError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if not as_list(brief.get("hooks")):
        print("ERROR: model returned no hooks", file=sys.stderr)
        return 1

    if args.output:
        payload = dict(brief)
        payload.setdefault("topic", topic)
        payload["sources"] = list(citations)
        write_json(repo_path(args.output), payload)

    if args.json:
        payload = dict(brief)
        payload["sources"] = list(citations)
        import json as _json

        print(_json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(render_brief(brief, citations))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
