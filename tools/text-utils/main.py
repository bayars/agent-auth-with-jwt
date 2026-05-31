"""
MCP Tool Server: Text Utils

Fast, stateless text transformation tools. No external dependencies.

Demonstrates: basic text return, scalar outputs, structured outputs,
pure-stdlib tools with zero I/O.

Tools:
  count_words     — word/line/char statistics
  format_json     — pretty-print a JSON string
  base64_encode   — encode UTF-8 text to base64
  base64_decode   — decode base64 back to UTF-8 text
  url_encode      — percent-encode a string for use in URLs
  url_decode      — decode percent-encoded string
  change_case     — convert text to upper / lower / title / snake / camel
  extract_lines   — filter lines by regex or substring
  diff_texts      — line-level unified diff of two strings
"""

import base64
import difflib
import json
import os
import re
import urllib.parse
from typing import Literal

import uvicorn
from fastmcp import FastMCP

PORT = int(os.environ.get("PORT", 8000))

mcp = FastMCP(
    name="Text Utils",
    instructions=(
        "Fast, stateless text-transformation tools. "
        "No external I/O — all processing is in-memory."
    ),
)


# ── Tools ──────────────────────────────────────────────────────────────────────

@mcp.tool()
async def count_words(text: str) -> dict:
    """
    Count words, lines, characters, and sentences in a block of text.

    Args:
        text: Any UTF-8 string.

    Returns a dict with:
        chars        (int)  total character count (including whitespace)
        chars_no_ws  (int)  character count excluding whitespace
        words        (int)  word count (whitespace-split)
        lines        (int)  line count (including empty lines)
        sentences    (int)  approximate sentence count (splits on . ! ?)
        paragraphs   (int)  paragraph count (blank-line separated)
        avg_word_len (float) average word length in characters
    """
    words = text.split()
    lines = text.splitlines()
    sentences = len(re.findall(r"[.!?]+", text)) or (1 if text.strip() else 0)
    paragraphs = len([p for p in re.split(r"\n\s*\n", text) if p.strip()])

    return {
        "chars": len(text),
        "chars_no_ws": len(text.replace(" ", "").replace("\n", "").replace("\t", "")),
        "words": len(words),
        "lines": len(lines),
        "sentences": sentences,
        "paragraphs": paragraphs or 1,
        "avg_word_len": round(
            sum(len(w) for w in words) / len(words), 2
        ) if words else 0.0,
    }


@mcp.tool()
async def format_json(
    json_string: str,
    indent: int = 2,
    sort_keys: bool = False,
) -> str:
    """
    Parse and pretty-print a JSON string.

    Args:
        json_string: Any valid JSON string (object, array, scalar).
        indent:      Indentation width in spaces (default 2).
        sort_keys:   Sort object keys alphabetically (default false).

    Returns the formatted JSON string, or an error message if the input
    is not valid JSON.
    """
    try:
        parsed = json.loads(json_string)
        return json.dumps(parsed, indent=indent, sort_keys=sort_keys, ensure_ascii=False)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc}") from exc


@mcp.tool()
async def base64_encode(text: str, url_safe: bool = False) -> str:
    """
    Base64-encode a UTF-8 string.

    Args:
        text:     The string to encode.
        url_safe: Use URL-safe alphabet (- and _ instead of + and /)
                  and strip padding (default false).

    Returns the base64-encoded ASCII string.
    """
    raw = text.encode("utf-8")
    if url_safe:
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    return base64.b64encode(raw).decode("ascii")


@mcp.tool()
async def base64_decode(encoded: str, url_safe: bool = False) -> str:
    """
    Decode a base64-encoded string back to UTF-8 text.

    Args:
        encoded:  Base64-encoded string (with or without padding).
        url_safe: Treat input as URL-safe base64 (default false).

    Returns the decoded UTF-8 string.
    """
    # Add padding if needed
    padded = encoded + "=" * (4 - len(encoded) % 4)
    try:
        if url_safe:
            raw = base64.urlsafe_b64decode(padded)
        else:
            raw = base64.b64decode(padded)
        return raw.decode("utf-8")
    except Exception as exc:
        raise ValueError(f"Base64 decode failed: {exc}") from exc


@mcp.tool()
async def url_encode(text: str, safe: str = "") -> str:
    """
    Percent-encode a string for safe use in a URL query parameter or path segment.

    Args:
        text: String to encode.
        safe: Characters that should NOT be encoded (default: none).
              Common values: "/" for path segments, "@:" for email-like strings.

    Returns the percent-encoded string.
    """
    return urllib.parse.quote(text, safe=safe)


@mcp.tool()
async def url_decode(encoded: str) -> str:
    """
    Decode a percent-encoded URL string.

    Args:
        encoded: Percent-encoded string, e.g. "hello%20world"

    Returns the decoded string.
    """
    return urllib.parse.unquote(encoded)


@mcp.tool()
async def change_case(
    text: str,
    to: Literal["upper", "lower", "title", "snake", "camel", "kebab"],
) -> str:
    """
    Convert a string to a different case style.

    Args:
        text: Input string.
        to:   Target case:
              upper  → "HELLO WORLD"
              lower  → "hello world"
              title  → "Hello World"
              snake  → "hello_world"
              camel  → "helloWorld"
              kebab  → "hello-world"

    Returns the converted string.
    """
    if to == "upper":
        return text.upper()
    if to == "lower":
        return text.lower()
    if to == "title":
        return text.title()

    # For structural cases, split on non-alphanumeric boundaries
    words = re.sub(r"[^a-zA-Z0-9]+", " ", text).strip().split()
    if not words:
        return text

    if to == "snake":
        return "_".join(w.lower() for w in words)
    if to == "kebab":
        return "-".join(w.lower() for w in words)
    if to == "camel":
        return words[0].lower() + "".join(w.capitalize() for w in words[1:])

    return text


@mcp.tool()
async def extract_lines(
    text: str,
    pattern: str,
    mode: Literal["contains", "regex", "startswith", "endswith"] = "contains",
    invert: bool = False,
    case_sensitive: bool = True,
) -> dict:
    """
    Filter lines from a block of text by a pattern.

    Like `grep` but available as an MCP tool.

    Args:
        text:           Multi-line input text.
        pattern:        Search pattern string.
        mode:           How to match — "contains" (substring), "regex",
                        "startswith", or "endswith". Default "contains".
        invert:         Return lines that do NOT match (like grep -v). Default false.
        case_sensitive: Case-sensitive match (default true).

    Returns a dict with:
        lines      (list[str])  matched lines
        count      (int)        number of matched lines
        total      (int)        total lines in input
    """
    all_lines = text.splitlines()
    flags = 0 if case_sensitive else re.IGNORECASE
    compare = pattern if case_sensitive else pattern.lower()

    def matches(line: str) -> bool:
        l = line if case_sensitive else line.lower()
        if mode == "contains":
            return compare in l
        if mode == "startswith":
            return l.startswith(compare)
        if mode == "endswith":
            return l.endswith(compare)
        if mode == "regex":
            return bool(re.search(pattern, line, flags))
        return False

    matched = [l for l in all_lines if matches(l) != invert]
    return {
        "lines": matched,
        "count": len(matched),
        "total": len(all_lines),
    }


@mcp.tool()
async def diff_texts(
    original: str,
    modified: str,
    context_lines: int = 3,
    label_a: str = "original",
    label_b: str = "modified",
) -> dict:
    """
    Produce a line-level unified diff between two strings.

    Useful for reviewing what changed between two versions of a file,
    config, or text block.

    Args:
        original:      The "before" text.
        modified:      The "after" text.
        context_lines: Lines of context around each change (default 3).
        label_a:       Label for the original (default "original").
        label_b:       Label for the modified (default "modified").

    Returns a dict with:
        diff        (str)   unified diff as a string (empty if identical)
        changed     (bool)  true if texts differ
        added       (int)   lines added
        removed     (int)   lines removed
    """
    a = original.splitlines(keepends=True)
    b = modified.splitlines(keepends=True)

    diff_lines = list(
        difflib.unified_diff(a, b, fromfile=label_a, tofile=label_b, n=context_lines)
    )
    diff_text = "".join(diff_lines)

    added = sum(1 for l in diff_lines if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in diff_lines if l.startswith("-") and not l.startswith("---"))

    return {
        "diff": diff_text,
        "changed": bool(diff_lines),
        "added": added,
        "removed": removed,
    }


# ── Health + entrypoint ───────────────────────────────────────────────────────
from starlette.responses import JSONResponse
from starlette.routing import Route

async def health(_):
    return JSONResponse({"status": "ok", "server": "mcp-text-utils"})

if __name__ == "__main__":
    app = mcp.http_app(transport="streamable-http")
    app.routes.insert(0, Route("/health", health))
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
