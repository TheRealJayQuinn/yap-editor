#!/usr/bin/env python3
"""A small Perplexity chat-API client, shared by the scripts that call it.

Stdlib only, to match the rest of the pipeline. Two callers use it today:
`plan_llm.py` (structural cut planning) and `research.py` (pre-shoot hooks).
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Dict, List, Sequence, Tuple


DEFAULT_BASE_URL = "https://api.perplexity.ai"
DEFAULT_API_KEY_ENV = "PERPLEXITY_API_KEY"


class PerplexityError(RuntimeError):
    """Anything that stops us getting a usable answer back."""


def api_key(env_var: str = DEFAULT_API_KEY_ENV) -> str:
    key = os.environ.get(env_var, "").strip()
    if not key:
        raise PerplexityError(
            f"no API key in ${env_var}. Set it, or use --dry-run to see the request."
        )
    return key


def chat(
    messages: Sequence[Dict[str, str]],
    *,
    api_key: str,
    base_url: str = DEFAULT_BASE_URL,
    model: str,
    temperature: float = 0.2,
    max_tokens: int = 2000,
    timeout: float = 90.0,
) -> Tuple[str, List[str]]:
    """POST a chat completion. Returns (content, citations)."""
    payload = {
        "model": model,
        "messages": list(messages),
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    request = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace") if hasattr(exc, "read") else ""
        raise PerplexityError(
            f"Perplexity API returned HTTP {exc.code}: {detail.strip() or exc.reason}"
        ) from exc
    except urllib.error.URLError as exc:
        raise PerplexityError(f"could not reach {base_url}: {exc.reason}") from exc
    try:
        data = json.loads(body)
        content = data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise PerplexityError(f"unexpected response shape from Perplexity API: {exc}") from exc
    citations = data.get("citations")
    if not isinstance(citations, list):
        citations = []
    return content, [str(item) for item in citations]


def extract_json_object(content: str) -> Dict[str, Any]:
    """Pull the first balanced JSON object out of a model response."""
    text = content.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    start = text.find("{")
    if start == -1:
        raise PerplexityError("model response contained no JSON object")
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                snippet = text[start : index + 1]
                try:
                    return json.loads(snippet)
                except ValueError as exc:
                    raise PerplexityError(f"model returned malformed JSON: {exc}") from exc
    raise PerplexityError("model response had an unbalanced JSON object")
