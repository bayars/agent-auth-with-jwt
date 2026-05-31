"""
MCP Tool Server: File Generator

Generates files of various formats (CSV, JSON, Markdown, ZIP) and returns
them as text or base64-encoded content.

Demonstrates: in-memory file generation, binary output (base64), multiple
file formats, structured return values.

Tools:
  generate_csv       — produce a CSV file from headers + rows
  generate_json_file — produce a formatted JSON file
  generate_markdown  — produce a Markdown document with sections
  generate_zip       — bundle multiple files into a base64 ZIP archive
"""

import base64
import csv
import io
import json
import os
import zipfile
from datetime import datetime

import uvicorn
from fastmcp import FastMCP
from pydantic import BaseModel, Field

PORT = int(os.environ.get("PORT", 8000))

mcp = FastMCP(
    name="File Generator",
    instructions=(
        "Tools that generate files in various formats. "
        "Text-based tools (CSV, JSON, Markdown) return the file contents as a string. "
        "Binary tools (ZIP) return base64-encoded content that must be decoded before saving."
    ),
)


# ── Pydantic models for complex inputs ────────────────────────────────────────

class MarkdownSection(BaseModel):
    heading: str = Field(description="Section heading (without # prefix)")
    level: int = Field(default=2, description="Heading level 1-4, default 2")
    content: str = Field(description="Section body (plain text or markdown)")
    code_block: str | None = Field(
        default=None,
        description="Optional code to append as a fenced code block"
    )
    code_lang: str = Field(default="", description="Language hint for fenced block, e.g. python")


class FileEntry(BaseModel):
    name: str = Field(description="Filename including extension, e.g. README.md")
    content: str = Field(description="File content as a UTF-8 string")


# ── Tools ─────────────────────────────────────────────────────────────────────

@mcp.tool()
async def generate_csv(
    headers: list[str],
    rows: list[list[str]],
    filename: str = "output.csv",
    delimiter: str = ",",
) -> dict:
    """
    Generate a CSV file from a list of headers and rows.

    Args:
        headers:   Column names, e.g. ["Name", "Age", "Email"]
        rows:      Data rows — each inner list must have the same length as headers.
                   e.g. [["Alice", "30", "alice@example.com"], ["Bob", "25", "bob@example.com"]]
        filename:  Suggested filename (default "output.csv")
        delimiter: Field delimiter character (default ","; use "\\t" for TSV)

    Returns a dict with:
        filename  (str)  suggested save name
        content   (str)  full CSV text, ready to write to disk
        rows      (int)  number of data rows generated
        size_bytes(int)  byte length of content
    """
    if not headers:
        raise ValueError("headers must not be empty")

    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=delimiter)
    writer.writerow(headers)
    writer.writerows(rows)
    content = buf.getvalue()

    return {
        "filename": filename,
        "content": content,
        "rows": len(rows),
        "size_bytes": len(content.encode()),
    }


@mcp.tool()
async def generate_json_file(
    data: dict | list,
    filename: str = "output.json",
    indent: int = 2,
    sort_keys: bool = False,
) -> dict:
    """
    Generate a pretty-printed JSON file from a dict or list.

    Args:
        data:      The Python object to serialise (dict or list)
        filename:  Suggested filename (default "output.json")
        indent:    Indentation spaces (default 2)
        sort_keys: Sort object keys alphabetically (default false)

    Returns a dict with:
        filename   (str)  suggested save name
        content    (str)  formatted JSON text
        size_bytes (int)  byte length
    """
    content = json.dumps(data, indent=indent, sort_keys=sort_keys, default=str)
    return {
        "filename": filename,
        "content": content,
        "size_bytes": len(content.encode()),
    }


@mcp.tool()
async def generate_markdown(
    title: str,
    sections: list[MarkdownSection],
    filename: str = "document.md",
    include_toc: bool = False,
) -> dict:
    """
    Generate a structured Markdown document from a title and sections.

    Each section has a heading, body text, and an optional fenced code block.
    Optionally prepend an auto-generated table of contents.

    Args:
        title:       Document title (becomes an H1 heading)
        sections:    List of section objects — see MarkdownSection schema
        filename:    Suggested filename (default "document.md")
        include_toc: Prepend a table of contents (default false)

    Returns a dict with:
        filename   (str)  suggested save name
        content    (str)  full Markdown text
        size_bytes (int)  byte length
        word_count (int)  approximate word count
    """
    lines: list[str] = [f"# {title}", ""]
    lines.append(
        f"*Generated {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}*"
    )
    lines.append("")

    if include_toc:
        lines.append("## Table of Contents")
        lines.append("")
        for s in sections:
            slug = s.heading.lower().replace(" ", "-")
            lines.append(f"- [{s.heading}](#{slug})")
        lines.append("")

    for s in sections:
        prefix = "#" * max(1, min(s.level, 4))
        lines.append(f"{prefix} {s.heading}")
        lines.append("")
        if s.content.strip():
            lines.append(s.content.strip())
            lines.append("")
        if s.code_block:
            fence = f"```{s.code_lang}" if s.code_lang else "```"
            lines.append(fence)
            lines.append(s.code_block.strip())
            lines.append("```")
            lines.append("")

    content = "\n".join(lines)
    return {
        "filename": filename,
        "content": content,
        "size_bytes": len(content.encode()),
        "word_count": len(content.split()),
    }


@mcp.tool()
async def generate_zip(
    files: list[FileEntry],
    archive_name: str = "archive.zip",
    compression: str = "deflated",
) -> dict:
    """
    Bundle multiple text files into a ZIP archive.

    Returns the archive as a base64-encoded string. The caller must
    base64-decode the 'content' field before writing it to disk.

    Args:
        files:        List of file objects with 'name' and 'content' fields.
                      e.g. [{"name": "README.md", "content": "# Hello"},
                             {"name": "data.json", "content": "{}"}]
        archive_name: Suggested archive filename (default "archive.zip")
        compression:  "deflated" (default, best compression) or "stored" (no compression)

    Returns a dict with:
        filename   (str)   suggested archive filename
        encoding   (str)   always "base64"
        content    (str)   base64-encoded ZIP bytes — decode before writing
        file_count (int)   number of files included
        size_bytes (int)   uncompressed total size of all files
        compressed_bytes (int) compressed ZIP size
    """
    if not files:
        raise ValueError("files must not be empty")

    comp = zipfile.ZIP_DEFLATED if compression == "deflated" else zipfile.ZIP_STORED
    buf = io.BytesIO()
    total_uncompressed = 0

    with zipfile.ZipFile(buf, mode="w", compression=comp) as zf:
        for f in files:
            data = f.content.encode("utf-8")
            total_uncompressed += len(data)
            zf.writestr(f.name, data)

    zip_bytes = buf.getvalue()
    return {
        "filename": archive_name,
        "encoding": "base64",
        "content": base64.b64encode(zip_bytes).decode("ascii"),
        "file_count": len(files),
        "size_bytes": total_uncompressed,
        "compressed_bytes": len(zip_bytes),
    }


# ── Health + entrypoint ───────────────────────────────────────────────────────
from starlette.responses import JSONResponse
from starlette.routing import Route

async def health(_):
    return JSONResponse({"status": "ok", "server": "mcp-file-generator"})

if __name__ == "__main__":
    app = mcp.http_app(transport="streamable-http")
    app.routes.insert(0, Route("/health", health))
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
