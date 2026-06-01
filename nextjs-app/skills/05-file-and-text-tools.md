# File Generation and Text Utility Tools

## File Generator (from `file-generator` MCP server)

| Tool | Returns | Output type |
|---|---|---|
| `generate_csv(headers, rows, filename, delimiter)` | `{filename, content, rows, size_bytes}` | Text (CSV) |
| `generate_json_file(data, filename, indent, sort_keys)` | `{filename, content, size_bytes}` | Text (JSON) |
| `generate_markdown(title, sections, filename, include_toc)` | `{filename, content, size_bytes, word_count}` | Text (Markdown) |
| `generate_zip(files, archive_name, compression)` | `{filename, encoding:"base64", content, file_count}` | Binary (base64) |

**For ZIP files**: the `content` field is base64-encoded. Remind the user to
decode it before saving: `base64 -d archive.zip.b64 > archive.zip`

**Markdown sections format:**
```json
[{"heading": "Overview", "level": 2, "content": "...", "code_block": "...", "code_lang": "python"}]
```

## Text Generator (from `text-generator` MCP server)

Large-text document generators — all return plain Markdown strings (can be multi-KB).

| Tool | Returns |
|---|---|
| `generate_readme(project_name, description, features, tech_stack, ...)` | Complete README.md |
| `generate_api_docs(service_name, base_url, version, endpoints)` | Full API reference |
| `generate_changelog(project_name, versions)` | Keep-a-Changelog format |
| `generate_report(report_title, author, executive_summary, sections)` | Executive report |

**ApiEndpoint format:**
```json
{"method": "POST", "path": "/users", "summary": "...", "auth_required": true,
 "request_body": {...}, "response_example": {...}, "error_codes": [400, 401]}
```

## Text Utils (from `text-utils` MCP server)

Fast, stateless, stdlib-only tools — no external I/O.

| Tool | Returns |
|---|---|
| `count_words(text)` | `{chars, words, lines, sentences, paragraphs, avg_word_len}` |
| `format_json(json_string, indent, sort_keys)` | Pretty-printed JSON string |
| `base64_encode(text, url_safe)` | Base64 string |
| `base64_decode(encoded, url_safe)` | Original UTF-8 string |
| `url_encode(text, safe)` | Percent-encoded string |
| `url_decode(encoded)` | Decoded string |
| `change_case(text, to)` | `to` = upper/lower/title/snake/camel/kebab |
| `extract_lines(text, pattern, mode, invert, case_sensitive)` | `{lines, count, total}` |
| `diff_texts(original, modified, context_lines, label_a, label_b)` | `{diff, changed, added, removed}` |
