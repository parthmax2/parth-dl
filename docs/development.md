# Development Guide

This guide is for people who want to use `parth-dl` inside another project, contribute
code, debug extraction problems, or ship a release.

## Requirements

- Python 3.9 or newer
- Git
- A terminal with internet access
- No runtime dependencies are required by the package itself

Development dependencies are installed through the `dev` extra:

```bash
pip install -e ".[dev]"
```

That currently installs `pytest` and `ruff`.

## Local Setup

Clone the repository:

```bash
git clone https://github.com/parthmax2/parth-dl.git
cd parth-dl
```

Create a virtual environment:

```bash
python -m venv .venv
```

Activate it on Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Activate it on macOS/Linux:

```bash
source .venv/bin/activate
```

Install the package in editable mode:

```bash
pip install -e ".[dev]"
```

Check the CLI:

```bash
parth-dl --version
parth-dl --help
```

If the `parth-dl` command is not found, use:

```bash
python -m parth_dl.cli --version
```

or make sure the virtual environment is activated.

## Common Developer Commands

Run tests:

```bash
python -m pytest
```

Run one test file:

```bash
python -m pytest tests/test_cli.py
```

Run lint:

```bash
python -m ruff check .
```

Run the CLI from the working tree:

```bash
python -m parth_dl.cli https://www.instagram.com/reel/Cxyz123AbCd/
```

Run the local HTTP API and web UI:

```bash
parth-dl serve --dir ./downloads --port 8000
```

Open:

```text
http://127.0.0.1:8000
```

## Testing a Real Public URL

Use verbose mode when checking an Instagram behavior change:

```bash
parth-dl -v -P ./downloads https://www.instagram.com/reel/Cxyz123AbCd/
```

Use JSON mode when you only want extraction metadata:

```bash
parth-dl --json https://www.instagram.com/reel/Cxyz123AbCd/
```

Use format listing when debugging rendition selection:

```bash
parth-dl --list-formats https://www.instagram.com/reel/Cxyz123AbCd/
```

Notes:

- Test with public content that works in a logged-out browser.
- Keep the default rate limiter on.
- Do not commit downloaded media, `.part` files, or local debug scripts.
- Direct CDN URLs from metadata are signed and expire quickly.

## Architecture

```text
parth_dl/
  __init__.py       Public package exports: download(), get_info(), InstagramDownloader
  cli.py            CLI parser, banner, JSON mode, exit-code mapping
  core.py           Download orchestration, output paths, resume handling
  extractors.py     Instagram extraction methods and fallback order
  server.py         Loopback HTTP API, job queue, web UI serving
  utils.py          URL checks, retry, rate limiter, file safety, output helpers
  web/index.html    Single-file browser UI
```

High-level flow:

```text
URL
  -> validate Instagram URL
  -> extract metadata through fallback methods
  -> select best/worst format
  -> validate CDN URL and redirects
  -> download to .part
  -> verify byte count
  -> promote to final filename
```

The extraction layer is intentionally separated from download orchestration. Instagram
changes often, so extractor fixes should be small, testable, and isolated whenever
possible.

## Public Contracts

Keep these stable unless the version is intentionally breaking:

- CLI flags in [cli.md](cli.md)
- CLI exit codes in [cli.md](cli.md#exit-codes)
- Python exports in `parth_dl.__all__`
- Metadata fields in [schema.md](schema.md)
- HTTP endpoints and status codes in [http-api.md](http-api.md)
- File safety behavior: no path traversal, no unsafe media hosts, no partial promoted as complete

When changing any public behavior, update the matching doc page and tests in the same
change.

## Adding a Feature

1. Decide the surface area: CLI, Python API, HTTP API, or internal only.
2. Add tests near the layer being changed.
3. Keep runtime dependencies at zero unless there is a strong reason.
4. Update docs for every public surface affected.
5. Run `python -m pytest` and `python -m ruff check .`.

Feature examples:

- CLI-only flag: update `parth_dl/cli.py`, `docs/cli.md`, and `tests/test_cli.py`.
- New metadata field: update extractor/core tests, `docs/schema.md`, and any API docs.
- Server endpoint: update `parth_dl/server.py`, `docs/http-api.md`, and `tests/test_server.py`.

## Debugging Instagram Extraction

Start with:

```bash
parth-dl -v --json "https://www.instagram.com/reel/Cxyz123AbCd/"
```

Check these possibilities:

| Problem | What it usually means |
|---|---|
| Works in browser only when logged in | The content is login-walled; anonymous download may not be possible |
| Browser says content unavailable | Deleted, region blocked, or private |
| CLI says rate limited | Instagram is throttling the IP; wait and retry later |
| Embed has only a thumbnail | The fallback extractor should try the logged-out Polaris flow |
| CDN URL returns 403 later | Signed CDN URL expired; extract fresh metadata |
| Video has no audio | Instagram may have returned a DASH/video-only rendition; choose combined H.264/AAC when available |

Useful checks:

```bash
parth-dl --list-formats URL
parth-dl --json URL
parth-dl -v URL
```

Do not add cookie-based flows unless the project explicitly decides to support
authenticated downloads. The current contract is public logged-out content only.

## Error Handling

Python callers should catch specific exceptions first:

```python
from parth_dl import DownloadError, NetworkError, RateLimitError, ValidationError

try:
    path = download(url)
except ValidationError:
    ...
except RateLimitError:
    ...
except NetworkError:
    ...
except DownloadError:
    ...
```

Shell callers should branch on exit codes:

```bash
parth-dl --quiet "$url"
case $? in
  0) echo "ok" ;;
  3) echo "network error" ;;
  4) echo "rate limited" ;;
  5) echo "invalid url" ;;
  *) echo "download failed" ;;
esac
```

HTTP callers should branch on status codes, not message text. See
[http-api.md](http-api.md#error-responses).

## Documentation Style

Write docs for the person trying to build something quickly:

- Start with the command or code they can run.
- State whether the example is CLI, Python, or HTTP.
- Link to the schema instead of repeating every field.
- Mention public-content limitations clearly.
- Keep examples copy-pasteable.
- Avoid depending on a specific real Instagram URL in permanent docs.

When docs mention the CLI caption, use:

```text
parth-dl  v1.2.0
Instagram Media Downloader · public content
Developed by Parthmax
```

## Release Checklist

Before publishing:

1. Update `parth_dl/__init__.py` version.
2. Update `CHANGELOG.md`.
3. Run `python -m pytest`.
4. Run `python -m ruff check .`.
5. Build and inspect the package.
6. Install the built wheel in a clean environment.
7. Smoke test `parth-dl --help`, `parth-dl --version`, and `parth-dl serve --no-open`.
8. Publish to PyPI.
9. Verify the PyPI page renders the README correctly.

Build commands:

```bash
python -m pip install build twine
python -m build
python -m twine check dist/*
```

## Pull Request Checklist

Before opening a PR:

- Tests pass locally.
- Ruff passes locally.
- New public behavior is documented.
- New errors use existing exception types or documented HTTP statuses.
- No downloaded media, credentials, cookies, or local debug files are committed.
- The change keeps Windows, macOS, and Linux behavior in mind.

For extractor PRs, include the failing public URL only if it is safe to share.
