"""
MCP Tool Server: Text Generator

Generates large text documents: READMEs, API documentation, changelogs,
and structured reports. All tools return plain strings (potentially large).

Demonstrates: large text output, parametric document generation, Pydantic
models for complex structured input.

Tools:
  generate_readme      — professional README.md for a software project
  generate_api_docs    — full API reference in Markdown
  generate_changelog   — structured CHANGELOG from a list of changes
  generate_report      — executive-style report from key-value data
"""

import os
from datetime import datetime
from typing import Literal

import uvicorn
from fastmcp import FastMCP
from pydantic import BaseModel, Field

PORT = int(os.environ.get("PORT", 8000))

mcp = FastMCP(
    name="Text Generator",
    instructions=(
        "Tools that generate large, structured text documents. "
        "All tools return a plain string (Markdown or plain text). "
        "Output can be several kilobytes — write it directly to a file or display in full."
    ),
)


# ── Pydantic models ────────────────────────────────────────────────────────────

class ApiEndpoint(BaseModel):
    method: str = Field(description="HTTP method: GET, POST, PUT, DELETE, PATCH")
    path: str = Field(description="URL path with placeholders, e.g. /users/{id}")
    summary: str = Field(description="One-line description of what the endpoint does")
    description: str = Field(default="", description="Longer description (optional)")
    auth_required: bool = Field(default=True, description="Whether Bearer token is required")
    request_body: dict | None = Field(
        default=None,
        description="Example request body as a JSON-serialisable dict (optional)"
    )
    response_example: dict | None = Field(
        default=None,
        description="Example successful response as a JSON-serialisable dict (optional)"
    )
    error_codes: list[int] = Field(
        default_factory=list,
        description="Expected HTTP error status codes, e.g. [400, 404, 401]"
    )


class ChangelogEntry(BaseModel):
    type: Literal["added", "changed", "fixed", "removed", "deprecated", "security"]
    description: str = Field(description="One-line change description")
    issue: str | None = Field(default=None, description="Issue/PR reference, e.g. #123")


class ChangelogVersion(BaseModel):
    version: str = Field(description="Semantic version string, e.g. 1.2.0")
    date: str = Field(description="Release date in YYYY-MM-DD format")
    changes: list[ChangelogEntry]


class ReportSection(BaseModel):
    title: str
    metrics: dict[str, str | int | float] = Field(
        default_factory=dict,
        description="Key-value metrics to render as a table"
    )
    findings: list[str] = Field(
        default_factory=list,
        description="Bullet-point findings"
    )
    recommendations: list[str] = Field(
        default_factory=list,
        description="Bullet-point recommendations"
    )


# ── Tools ──────────────────────────────────────────────────────────────────────

@mcp.tool()
async def generate_readme(
    project_name: str,
    description: str,
    features: list[str],
    tech_stack: list[str] | None = None,
    installation_steps: list[str] | None = None,
    usage_example: str | None = None,
    env_vars: list[dict] | None = None,
    license_name: str = "MIT",
    repo_url: str = "",
) -> str:
    """
    Generate a professional README.md for a software project.

    Produces a multi-section Markdown document with badges, description,
    features, tech stack, installation instructions, usage examples, and more.

    Args:
        project_name:       Display name of the project
        description:        One to three sentence project description
        features:           Bullet list of key features
        tech_stack:         Technologies used, e.g. ["Python 3.12", "FastMCP", "Redis"]
        installation_steps: Step-by-step install commands or instructions
        usage_example:      Code or shell example showing basic usage
        env_vars:           List of {"name": "VAR", "description": "...", "required": true}
        license_name:       License identifier (default "MIT")
        repo_url:           GitHub/GitLab URL (used in badge links)

    Returns the complete README.md content as a string (~1-3 KB).
    """
    import json as _json

    lines = [
        f"# {project_name}",
        "",
        f"> {description}",
        "",
    ]

    # Features
    lines += ["## Features", ""]
    for feat in features:
        lines.append(f"- {feat}")
    lines.append("")

    # Tech stack
    if tech_stack:
        lines += ["## Tech Stack", ""]
        for tech in tech_stack:
            lines.append(f"- {tech}")
        lines.append("")

    # Installation
    if installation_steps:
        lines += ["## Installation", ""]
        for i, step in enumerate(installation_steps, 1):
            lines.append(f"{i}. {step}")
        lines.append("")

    # Usage
    if usage_example:
        lines += ["## Usage", "", "```", usage_example.strip(), "```", ""]

    # Environment variables
    if env_vars:
        lines += ["## Environment Variables", ""]
        lines.append("| Variable | Description | Required |")
        lines.append("|---|---|---|")
        for ev in env_vars:
            name = ev.get("name", "")
            desc = ev.get("description", "")
            req = "✓" if ev.get("required", False) else ""
            lines.append(f"| `{name}` | {desc} | {req} |")
        lines.append("")

    # License
    lines += [
        "## License",
        "",
        f"[{license_name}](LICENSE)",
        "",
    ]

    return "\n".join(lines)


@mcp.tool()
async def generate_api_docs(
    service_name: str,
    base_url: str,
    version: str,
    endpoints: list[ApiEndpoint],
    auth_description: str = "Pass a Keycloak JWT as `Authorization: Bearer <token>`.",
) -> str:
    """
    Generate a full API reference document in Markdown.

    For each endpoint, renders the HTTP method/path, description, auth requirement,
    request body example, response example, and possible error codes.

    Args:
        service_name:       Name shown at the top of the document
        base_url:           Base URL, e.g. https://api.example.com/v1
        version:            API version string, e.g. "v1.2"
        endpoints:          List of ApiEndpoint objects (method, path, summary, ...)
        auth_description:   One paragraph describing how to authenticate

    Returns the complete API documentation as Markdown (~2-10 KB depending on
    the number of endpoints).
    """
    import json as _json

    now = datetime.utcnow().strftime("%Y-%m-%d")
    lines = [
        f"# {service_name} API Reference",
        "",
        f"**Version:** {version}  |  **Base URL:** `{base_url}`  |  **Updated:** {now}",
        "",
        "---",
        "",
        "## Authentication",
        "",
        auth_description,
        "",
        "---",
        "",
        "## Endpoints",
        "",
    ]

    # Build a summary table
    lines += ["| Method | Path | Summary | Auth |", "|---|---|---|---|"]
    for ep in endpoints:
        auth_badge = "🔒" if ep.auth_required else "🔓"
        lines.append(
            f"| `{ep.method}` | `{ep.path}` | {ep.summary} | {auth_badge} |"
        )
    lines += ["", "---", ""]

    # Full detail for each endpoint
    for ep in endpoints:
        lines.append(f"### `{ep.method}` {ep.path}")
        lines.append("")
        lines.append(f"**Summary:** {ep.summary}")
        if ep.description:
            lines.append("")
            lines.append(ep.description)
        lines.append("")
        lines.append(
            f"**Auth required:** {'Yes — Bearer JWT' if ep.auth_required else 'No'}"
        )
        lines.append("")

        if ep.request_body:
            lines.append("**Request body (JSON):**")
            lines.append("```json")
            lines.append(_json.dumps(ep.request_body, indent=2))
            lines.append("```")
            lines.append("")

        if ep.response_example:
            lines.append("**Response (200):**")
            lines.append("```json")
            lines.append(_json.dumps(ep.response_example, indent=2))
            lines.append("```")
            lines.append("")

        if ep.error_codes:
            lines.append("**Error codes:** " + ", ".join(f"`{c}`" for c in ep.error_codes))
            lines.append("")

        lines.append("---")
        lines.append("")

    return "\n".join(lines)


@mcp.tool()
async def generate_changelog(
    project_name: str,
    versions: list[ChangelogVersion],
    include_unreleased: bool = False,
) -> str:
    """
    Generate a CHANGELOG.md following the Keep-a-Changelog format.

    Args:
        project_name:       Name of the project
        versions:           List of ChangelogVersion objects — each has a version
                            string, date, and list of typed changes.
        include_unreleased: Prepend an [Unreleased] section header (default false)

    Returns CHANGELOG.md content. Each version is grouped into Added, Changed,
    Fixed, Removed, Deprecated, and Security sub-sections as applicable.
    """
    type_order = ["security", "added", "changed", "fixed", "deprecated", "removed"]
    type_label = {
        "added": "Added",
        "changed": "Changed",
        "fixed": "Fixed",
        "removed": "Removed",
        "deprecated": "Deprecated",
        "security": "Security",
    }

    lines = [
        f"# Changelog — {project_name}",
        "",
        "All notable changes to this project will be documented here.",
        "Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).",
        "",
    ]

    if include_unreleased:
        lines += ["## [Unreleased]", ""]

    for ver in versions:
        lines.append(f"## [{ver.version}] — {ver.date}")
        lines.append("")

        # Group changes by type
        grouped: dict[str, list[ChangelogEntry]] = {}
        for ch in ver.changes:
            grouped.setdefault(ch.type, []).append(ch)

        for t in type_order:
            if t not in grouped:
                continue
            lines.append(f"### {type_label[t]}")
            lines.append("")
            for ch in grouped[t]:
                ref = f" ({ch.issue})" if ch.issue else ""
                lines.append(f"- {ch.description}{ref}")
            lines.append("")

    return "\n".join(lines)


@mcp.tool()
async def generate_report(
    report_title: str,
    author: str,
    executive_summary: str,
    sections: list[ReportSection],
    classification: str = "INTERNAL",
) -> str:
    """
    Generate a structured executive-style report in Markdown.

    Each section can contain metrics (rendered as a table), findings, and
    recommendations. Suitable for incident reports, sprint reviews, security
    assessments, etc.

    Args:
        report_title:       Report title
        author:             Author name or team
        executive_summary:  2-5 sentence overview for decision-makers
        sections:           List of ReportSection — each has title, metrics,
                            findings, and recommendations
        classification:     Label shown at top and bottom (default "INTERNAL")

    Returns a complete Markdown report (~2-20 KB depending on section count).
    """
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"<!-- {classification} -->",
        f"# {report_title}",
        "",
        f"| | |",
        "|---|---|",
        f"| **Author** | {author} |",
        f"| **Date** | {now} |",
        f"| **Classification** | {classification} |",
        "",
        "---",
        "",
        "## Executive Summary",
        "",
        executive_summary.strip(),
        "",
        "---",
        "",
    ]

    for section in sections:
        lines.append(f"## {section.title}")
        lines.append("")

        if section.metrics:
            lines.append("### Metrics")
            lines.append("")
            lines.append("| Metric | Value |")
            lines.append("|---|---|")
            for k, v in section.metrics.items():
                lines.append(f"| {k} | {v} |")
            lines.append("")

        if section.findings:
            lines.append("### Findings")
            lines.append("")
            for f in section.findings:
                lines.append(f"- {f}")
            lines.append("")

        if section.recommendations:
            lines.append("### Recommendations")
            lines.append("")
            for r in section.recommendations:
                lines.append(f"1. {r}")
            lines.append("")

        lines.append("---")
        lines.append("")

    lines.append(f"*{classification} — {report_title}*")
    return "\n".join(lines)


# ── Health + entrypoint ───────────────────────────────────────────────────────
from starlette.responses import JSONResponse
from starlette.routing import Route

async def health(_):
    return JSONResponse({"status": "ok", "server": "mcp-text-generator"})

if __name__ == "__main__":
    app = mcp.http_app(transport="streamable-http")
    app.routes.insert(0, Route("/health", health))
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
