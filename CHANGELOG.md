# Changelog

All notable changes to parth-dl are documented here.
This project adheres to [Semantic Versioning](https://semver.org/).

## [1.1.0] — 2026-07-13

### Added

- **Interactive mode** (`-i`, `--interactive`) — keeps prompting for the next URL after
  each download instead of making you re-run the command. Automatically disabled when
  stdin/stdout is not a terminal, so it can never hang a script.
- **Clickable results** — finished files print as OSC 8 terminal hyperlinks pointing at
  their `file://` URI, so you can click straight through to your video player. Terminals
  without OSC 8 support get the plain URI. Set `NO_HYPERLINKS=1` to opt out.
- **`parth-dl serve`** — a local HTTP JSON API and web UI, so any app in any language can
  drive the downloader. Loopback-only, with DNS-rebinding protection, no CORS header, and
  a path-traversal-safe file route. See [docs/http-api.md](docs/http-api.md).
- **Web UI** — paste a link, preview it, watch a live progress bar, click to save. Queue
  up multiple links and they download in the background.
- **`progress_hook`** on `InstagramDownloader` — `callable(downloaded_bytes, total_bytes)`,
  for reporting progress in your own UI.
- **Documentation** — [`docs/`](docs/) now covers the CLI, the Python API, the HTTP API, the
  metadata schema, and copy-paste recipes for Node, Go, PHP, Discord and Bash.
- **CI** — tests now run on Python 3.8–3.13 across Linux, macOS and Windows, with `ruff`
  and a packaging smoke check.

### Changed

- **Packaging migrated to `pyproject.toml`** (PEP 621). `setup.py` and `requirements.txt`
  are removed.
- `ValidationError` is now exported from the top-level package.
- README restructured around the three integration surfaces.

### Fixed

- Package metadata claimed `__author__ = "Parth"` while the distribution said
  "Saksham Pathak (Parthmax)". Now consistent.
- The Python version badge claimed 3.7+, but the code requires 3.8+.

### Tests

- Grown from 30 to **91**. The extraction layer — previously untested, and the most
  fragile part of the package — now has fixture-based coverage of the API, GraphQL and
  embed parsers plus the fallback chain. The CLI and server layers are covered end to end.

## [1.0.1]

- Initial public release: reels, posts, carousels and profile pictures; resumable
  downloads; rate limiting; retry with exponential backoff.
