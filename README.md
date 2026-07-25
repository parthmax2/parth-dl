# parth-dl - Lightweight Python Instagram Video Downloader

**parth-dl** is a lightweight, open-source Instagram video downloader for public reels,
posts, carousels, and profile pictures. It is built in Python with **zero runtime
dependencies** and can be used as a command-line tool, a Python package, or a local
JSON API.

Designed for developers who want a small Instagram downloader package that is easy to
install, script, and embed without pulling in a large dependency tree.

> Developed by [Parthmax](https://github.com/parthmax2) for public Instagram content.

[![PyPI](https://img.shields.io/pypi/v/parth-dl.svg)](https://pypi.org/project/parth-dl/)
[![CI](https://github.com/parthmax2/parth-dl/actions/workflows/ci.yml/badge.svg)](https://github.com/parthmax2/parth-dl/actions/workflows/ci.yml)
[![Python Version](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Downloads](https://static.pepy.tech/personalized-badge/parth-dl?period=total&units=international_system&left_color=grey&right_color=blue&left_text=Downloads)](https://pypi.org/project/parth-dl/)

---

## Demo

<div align="center">
  <img src="cli.gif" alt="parth-dl lightweight Instagram video downloader CLI demo with progress bar" width="720px">
  <p><em>Minimal CLI, clean progress bar, saved file path, and final summary.</em></p>
</div>

---

## Install

```bash
pip install parth-dl
```

Requires Python 3.9 or newer.

---

## Quickstart

```bash
# Download a public Instagram reel with audio
parth-dl https://www.instagram.com/reel/Cxyz123AbCd/

# Download multiple URLs
parth-dl https://www.instagram.com/p/AAA/ https://www.instagram.com/reel/BBB/

# Keep prompting for the next URL
parth-dl -i

# Open the local web UI
parth-dl serve
```

```python
from parth_dl import download

download("https://www.instagram.com/reel/Cxyz123AbCd/")
```

Some Instagram links are served behind a login wall even when they look public in a
browser. parth-dl works best with public reels/posts/profile pictures that Instagram
allows logged-out clients to access.

---

## Supported Content

| Content type | Status | Notes |
|---|---:|---|
| Public reels | Supported | Downloads video with audio when Instagram exposes it |
| Public posts | Supported | Images, videos, and mixed carousels |
| Profile pictures | Supported | Works without login for public profiles |
| Private posts/accounts | Not supported | Requires authentication |
| Stories and highlights | Not supported | Requires authentication |
| User feed scraping | Not supported | Listing a user's posts requires authentication |
| Login-only public links | Limited | Instagram may return a login wall without cookies |

---

## Usage Modes

| Mode | Use when | Docs |
|---|---|---|
| **CLI** | You want terminal downloads, shell scripts, CI, `--json`, or typed exit codes. | [docs/cli.md](docs/cli.md) |
| **Python package** | You want to call `download()`, `get_info()`, or `InstagramDownloader` from Python. | [docs/python-api.md](docs/python-api.md) |
| **Local HTTP API** | You want JSON over localhost for Node, Go, PHP, browser apps, or other languages. | [docs/http-api.md](docs/http-api.md) |
| **Web UI** | You want a local paste-and-download browser interface. | [docs/web-ui.md](docs/web-ui.md) |

Returned metadata is documented in [docs/schema.md](docs/schema.md). Integration
examples for Node, Go, PHP, Discord, and Bash are in [docs/recipes.md](docs/recipes.md).

---

## Features

- **Zero runtime dependencies** - pure Python standard library
- **Minimal CLI** - compact caption, clean status rows, progress bar, and summary
- **Reels, posts, carousels, and profile pictures** - one tool for common public media
- **Resumable downloads** - interrupted transfers continue safely when possible
- **Clickable results** - supported terminals can open completed file paths directly
- **Interactive mode** - `-i` keeps prompting for the next URL
- **Batch downloads** - pass multiple URLs or use `--batch-file`
- **JSON output** - use `--json` for scripts and automation
- **Local web UI** - `parth-dl serve` opens a paste-and-download interface
- **Rate limiting and backoff** - reduces request spikes and retries transient failures
- **Cross-platform** - Windows, macOS, and Linux

---

## Local Web UI

```bash
parth-dl serve
```

The web UI runs on `http://127.0.0.1:8000`. Paste a public Instagram URL, preview the
job, watch progress, and save the result. It is loopback-only, has no CORS header, and
rejects non-loopback `Host` headers so random websites cannot drive your local
downloader.

See [docs/web-ui.md](docs/web-ui.md) for the full browser guide and
[docs/http-api.md](docs/http-api.md#security-notes) for server security details.

---

## Limitations

parth-dl does **not** log in to Instagram and does **not** bypass access controls.

Unsupported cases include private posts, private accounts, stories, highlights, user feed
scraping, and links where Instagram only serves media to authenticated users. For those
cases, Instagram may return a login page instead of usable media metadata.

---

## Security And Ethics

- Media downloads are restricted to Instagram/CDN hosts discovered from Instagram pages
- Filenames are sanitized to avoid path traversal, control characters, and reserved names
- Network requests use timeouts and retry limits
- The local server only binds to loopback by default
- No runtime dependency tree means a smaller supply-chain surface

Use this project for educational, personal, and research purposes. You are responsible
for complying with Instagram's Terms of Service and the laws that apply to you.

---

## Architecture

```text
parth_dl/
├── __init__.py      # Public API: download(), get_info(), InstagramDownloader
├── core.py          # Extraction -> format selection -> resumable transfer
├── extractors.py    # Multi-layer extraction fallbacks
├── utils.py         # Retry, rate limiting, sanitization, validation, progress
├── cli.py           # argparse CLI
├── server.py        # Local JSON API + web UI
└── web/index.html   # Single-file web UI
```

Instagram can return different responses from different endpoints, so parth-dl tries
multiple public extraction paths before it reports a failure.

---

## Development

```bash
git clone https://github.com/parthmax2/parth-dl.git
cd parth-dl
pip install -e ".[dev]"

pytest
ruff check .
python scripts/render_cli_gif.py
```

The test suite currently collects 134 tests. Tests run against a real loopback HTTP
server for download, resume, range handling, truncation, retry, CLI, and API behavior.

---

## Contributing

Contributions, fixes, docs improvements, extractor updates, and new ideas are welcome.
Fork the repo, create a branch, commit your change, and open a pull request.

If you build something with `parth-dl`, tag
[@parthmax](https://instagram.com/parthmax).

---

## Author

**Saksham Pathak (Parthmax)** - Generative AI Engineer, Python Developer, and Open
Source Creator

- [Website](https://parthmax.in/)
- [GitHub](https://github.com/parthmax2)
- [LinkedIn](https://linkedin.com/in/sakshampathak)
- [Hugging Face](https://huggingface.co/parthmax)
- [Instagram](https://instagram.com/parthmax)

---

## License

MIT - see [LICENSE](LICENSE). Provided as-is, without warranty.
