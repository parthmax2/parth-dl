
# ⚡ parth-dl — Instagram Downloader CLI by Saksham Pathak (Parthmax)

**parth-dl** is a fast, open-source **Instagram Reels, Posts, and Profile Picture Downloader** built entirely in Python.
Use it three ways — a **command-line tool**, a **Python library**, or a **local HTTP API** that any app in any language can call.

🧠 Designed for automation • ⚙️ Developer-friendly • 🪶 Zero Dependencies • 🔐 Secure-by-default

> Keywords: instagram downloader, python instagram downloader, reels downloader, instagram scraper, insta video downloader, parth-dl, parthmax, saksham pathak, python cli, open source downloader

---

[![PyPI](https://img.shields.io/pypi/v/parth-dl.svg)](https://pypi.org/project/parth-dl/)
[![CI](https://github.com/parthmax2/parth-dl/actions/workflows/ci.yml/badge.svg)](https://github.com/parthmax2/parth-dl/actions/workflows/ci.yml)
[![Python Version](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Downloads](https://static.pepy.tech/personalized-badge/parth-dl?period=total&units=international_system&left_color=grey&right_color=blue&left_text=Downloads)](https://pypi.org/project/parth-dl/)

> Built by [**@parthmax_**](https://instagram.com/parthmax_) — Minimal, Fast, and Developer-Centric.

---

## ⚡ Quickstart

```bash
pip install parth-dl
```

```bash
# Download a reel (with audio)
parth-dl https://www.instagram.com/reel/Cxyz123AbCd/

# Keep going — prompts for the next URL after each download
parth-dl -i

# Open the web UI in your browser
parth-dl serve
```

```python
from parth_dl import download
download("https://www.instagram.com/reel/Cxyz123AbCd/")
```

---

## 🎬 Demo

<div align="center">
  <img src="cli.gif" alt="parth-dl CLI demo" width="720px">
  <p><em>Download Instagram reels, posts, or profile pictures — directly from your terminal.</em></p>
</div>

---

## 🧩 Three ways to use it

|  | Use when | Docs |
|---|---|---|
| **CLI** | Terminal, shell scripts, CI. `--json` + typed exit codes make it scriptable. | [docs/cli.md](docs/cli.md) |
| **Python library** | You're in Python. `from parth_dl import download, get_info`. | [docs/python-api.md](docs/python-api.md) |
| **HTTP API** | You're *not* in Python. `parth-dl serve` → JSON over localhost, for Node, Go, PHP, a browser… | [docs/http-api.md](docs/http-api.md) |

The dict every surface returns is documented field-by-field in **[docs/schema.md](docs/schema.md)** —
that's the contract to build on. Copy-paste integrations for Node, Go, PHP, Discord and
Bash are in **[docs/recipes.md](docs/recipes.md)**.

---

## 🚀 Features

- ✅ **Reels** — full video with synchronized audio
- ✅ **Posts** — single images, videos, and mixed carousels
- ✅ **Profile pictures** — HD, no login
- ✅ **Resumable downloads** — interrupted transfers pick up where they left off; a partial file is never mistaken for a complete one
- ✅ **Clickable results** — finished files print as terminal hyperlinks that open in your player
- ✅ **Interactive mode** — `-i` keeps prompting for the next URL
- ✅ **Web UI** — `parth-dl serve` for a paste-a-link interface with a live progress bar and a download queue
- ✅ **Zero dependencies** — pure Python standard library, no supply-chain risk
- ✅ **Smart rate limiting** — 30 req/min sliding window, avoids IP bans
- ✅ **Jittered exponential backoff** — resilient to transient network failures
- ✅ **Cross-platform** — Windows, macOS, Linux; Python 3.8+

---

## 🌐 Web UI

```bash
parth-dl serve
```

Opens a local page at `http://127.0.0.1:8000`: paste a link, see a preview, watch a real
progress bar, click to save. Queue up as many links as you like — they download in the
background while you paste the next one.

It's loopback-only, has no CORS header, and rejects non-loopback `Host` headers, so no
website you visit can drive your downloader. See [docs/http-api.md](docs/http-api.md#security).

---

## 🧬 Architecture

```
parth_dl/
├── __init__.py      # Public API: download(), get_info(), InstagramDownloader
├── core.py          # Orchestration: extraction -> format selection -> resumable transfer
├── extractors.py    # Multi-layer extraction: Embed -> GraphQL -> API, with fallback
├── utils.py         # Retry, rate limiting, sanitization, validation, progress
├── cli.py           # argparse CLI
├── server.py        # `parth-dl serve` — JSON API + web UI
└── web/index.html   # Single-file UI (works served, or static as a landing page)
```

**Multi-layer fallback extraction.** Instagram will happily 403 one endpoint while another
still answers, so every extraction method gets its turn before parth-dl gives up.

---

## 🔒 Security & ethics

- **Zero dependencies** — nothing but the standard library, no supply-chain surface
- **URL validation** — media is only ever fetched from Instagram's own CDN hosts, never an arbitrary URL
- **Filename sanitization** — path traversal, Windows reserved names, control characters
- **Timeout-safe requests** — no hangs
- **Loopback-only server** — with DNS-rebinding protection

⚠️ **Public content only.** Stories, highlights, private accounts, and listing a user's
posts all require authentication and are **not supported**.

*For educational, personal, and research use.* You are solely responsible for complying
with Instagram's Terms of Service and applicable law.

---

## 🧪 Development

```bash
git clone https://github.com/parthmax2/parth-dl.git
cd parth-dl
pip install -e ".[dev]"

pytest          # 91 tests
ruff check .
```

Tests run against a real loopback HTTP server rather than mocks, so resume, `Range`
handling, truncation and retry behaviour are exercised for real.

---

## 🤝 Contributing

Contributions and PRs welcome — fork, branch, commit, open a PR. If you build something
with `parth-dl`, tag [@parthmax_](https://instagram.com/parthmax_).

---

## 📝 License

**MIT** — see [LICENSE](LICENSE). Provided *"as is"*, without warranty.

---

## 👤 Author

**Saksham Pathak (Parthmax)** — Generative AI Engineer | Python Developer | Open Source Creator

* 🌐 [parthmax.in](https://parthmax.in/)
* 🧑‍💻 [GitHub](https://github.com/parthmax2)
* 💼 [LinkedIn](https://linkedin.com/in/sakshampathak)
* 🤗 [Hugging Face](https://huggingface.co/parthmax)
* 📷 [Instagram](https://instagram.com/parthmax_)

### Related projects

* [FALCON](https://huggingface.co/spaces/parthmax/FALCON) — Fake News Analysis & Verification System
* [FaceAging AI](https://huggingface.co/spaces/parthmax/FaceAging-AI) — AI-based Face Aging & Transformation
* [100 Best GenAI Projects](https://github.com/parthmax2/100-Best-GenAI-Projects-2025) — Curated open-source index

---

<div align="center">

⭐ *Star the repo if you find it useful*
💡 *Built with ❤️ and Python by [Parthmax](https://github.com/parthmax2)*

</div>
