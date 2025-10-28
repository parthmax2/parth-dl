
# ⚡ parth-dl — Instagram Downloader CLI by Saksham Pathak (Parthmax)

**parth-dl** is a fast, open-source **Instagram Reels, Posts, and Profile Picture Downloader** built entirely in Python.  
It provides a clean and reliable **command-line interface (CLI)** for developers who want to extract or download public Instagram media without using any third-party APIs, tokens, or logins.

🧠 Designed for automation • ⚙️ Developer-friendly • 🪶 Zero Dependencies • 🔐 Secure-by-default  

> Keywords: instagram downloader, python instagram downloader, reels downloader, instagram scraper, insta video downloader, parth-dl, parthmax, saksham pathak, python cli, open source downloader

---

[![PyPI](https://img.shields.io/pypi/v/parth-dl.svg)](https://pypi.org/project/parth-dl/)
[![Python Version](https://img.shields.io/badge/python-3.7+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Code Style](https://img.shields.io/badge/code%20style-clean-black.svg)]()
[![Downloads](https://static.pepy.tech/personalized-badge/parth-dl?period=total&units=international_system&left_color=grey&right_color=blue&left_text=Downloads)](https://pypi.org/project/parth-dl/)

> Built by [**@parthmax_**](https://instagram.com/parthmax_) — Minimal, Fast, and Developer-Centric.

---

## 🧩 About

`parth-dl` is not another bloated downloader. It’s a **developer-oriented, dependency-free** toolkit that leverages Instagram’s underlying page and GraphQL data endpoints to extract high-resolution media metadata and files.  

It uses a **multi-layered extraction pipeline** with intelligent fallback logic to ensure successful downloads of **Instagram Reels, Photos, Carousels, and Profile Pictures**, even when APIs change or fail.

Built for:
- 🧰 **Developers** who need a CLI or API-level integration  
- 🤖 **Automation scripts** and research tools  
- 🧪 **Learning projects** exploring web scraping and data extraction  

---

## 🎬 Demo

<div align="center">
  <img src="cli.gif" alt="parth-dl CLI demo" width="720px">
  <p><em>Quickly download Instagram reels, posts, or profile pictures — directly from your terminal.</em></p>
</div>

---

## 🚀 Features

- ✅ **Reels Downloader** — Fetches full reels with synchronized audio and video  
- ✅ **Post Downloader** — Supports single and multi-image/carousel posts  
- ✅ **Profile Picture Downloader** — Downloads HD profile images instantly  
- ✅ **Zero Dependencies** — Pure Python, no external libraries  
- ✅ **Smart Rate Limiting** — Avoids IP bans and throttling  
- ✅ **Exponential Backoff & Retry Logic** — Resilient against network or request failures  
- ✅ **Cross-Platform CLI Tool** — Works seamlessly on macOS, Linux, and Windows  
- ✅ **Public Data Only** — No login, tokens, or authentication required  
- ✅ **Python API Ready** — Use as a package in your own projects or automation scripts  

---

## ⚡ Installation

### 🔹 From PyPI
Install the latest stable release directly from [PyPI](https://pypi.org/project/parth-dl/):

```bash
pip install parth-dl
````

### 🔹 From Source

If you prefer the latest development version:

```bash
git clone https://github.com/parthmax2/parth-dl.git
cd parth-dl
pip install -e .
```

---

## 🧠 Usage

### 💻 CLI Examples

```bash
# Download a Reel (with audio)
parth-dl https://www.instagram.com/reel/ABC123/

# Download a single post
parth-dl https://www.instagram.com/p/XYZ456/

# Download carousel/multi-image post
parth-dl https://www.instagram.com/p/POST789/

# Download profile picture
parth-dl https://www.instagram.com/username/

# Custom output file
parth-dl https://www.instagram.com/reel/ABC123/ -o my_video.mp4

# List all available formats
parth-dl https://www.instagram.com/reel/ABC123/ --list-formats

# Verbose mode for debugging
parth-dl https://www.instagram.com/reel/ABC123/ -v
```

### 🐍 Python API Example

You can also integrate `parth-dl` directly into your Python code:

```python
from parth_dl import InstagramDownloader

dl = InstagramDownloader(verbose=True)

# Download directly
dl.download("https://www.instagram.com/reel/ABC123/")

# Fetch metadata only
info = dl.get_info("https://www.instagram.com/reel/ABC123/")
print(info)
```

**Quick one-liner:**

```python
from parth_dl import download
download("https://www.instagram.com/reel/ABC123/")
```

---

## 🧬 Internal Architecture

```
parth-dl/
├── parth_dl/
│   ├── __init__.py      # Package entry and exports
│   ├── core.py          # Main orchestrator and command handler
│   ├── extractors.py    # Multi-layer data extraction (GraphQL, Embed, API, HTML)
│   ├── utils.py         # Retry logic, sanitization, rate limiting
│   └── cli.py           # CLI interface for end users
├── setup.py
├── README.md
└── requirements.txt     # (Empty — no dependencies)
```

### ✨ Technical Highlights

* **4-layer fallback extraction** → ensures maximum reliability
* **Token bucket rate limiter (30 req/min)** → avoids bans
* **Jittered exponential backoff** → smooth handling of transient errors
* **URL and filename sanitization** → prevents injection and invalid filenames
* **CLI-friendly architecture** → extensible, testable, and minimal

---

## 🔒 Security & Ethics

* 100% **standard library** → no external dependencies, no supply chain risk
* **Input validation** → prevents malicious URL injections
* **Timeout-safe HTTP requests** → avoids hangs and freezes
* **Ethical scraping** → adheres to fair-use and ToS boundaries

⚠️ *Use responsibly. For educational, personal, and research use only.*
You are solely responsible for complying with Instagram’s ToS and applicable laws.

---

## 🧰 Developer Notes

This project was engineered with:

* 🐍 **Python 3.7+**
* 🧩 Modular, extensible design
* 💬 Clean CLI with argparse
* 🧪 Error-tolerant architecture for production-safe automation
* 🌐 Tested with multiple Instagram endpoints and URL patterns

If you’re a developer looking to **embed Instagram download functionality** into your automation pipeline, CLI tools, or data research systems — `parth-dl` is a perfect, lightweight foundation.

---

## 🔗 Related Projects

* [FaceAging AI](https://huggingface.co/spaces/parthmax/FaceAging-AI) — AI-based Face Aging & Transformation Web App
* [FALCON](https://huggingface.co/spaces/parthmax/FALCON) — Fake News Analysis & Verification System
* [Dynamic QR Redirector](https://github.com/parthmax2/dynamic-qr) — FastAPI-powered dynamic QR generator and redirect manager

All open-source developer tools by **[Saksham Pathak (Parthmax)](https://github.com/parthmax2)**.

---

## 🤝 Contributing

Contributions, suggestions, and PRs are welcome!

1. Fork this repository
2. Create a new branch (`feature/new-idea`)
3. Commit your improvements
4. Push and open a PR 🚀

If you build something cool using `parth-dl`, feel free to share it on social media and tag [@parthmax_](https://instagram.com/parthmax_).

---

## 📝 License

**MIT License** — See [LICENSE](LICENSE) for full text.
Provided *“as is”* without warranty. The author is not responsible for misuse or policy violations.

---

## 👤 Author

**Saksham Pathak (Parthmax)**
🎯 Generative AI Engineer | Python Developer | Open Source Creator

* 📷 [Instagram](https://instagram.com/parthmax_)
* 💼 [LinkedIn](https://linkedin.com/in/sakshampathak)
* 🤗 [Hugging Face](https://huggingface.co/parthmax)
* 🧑‍💻 [GitHub](https://github.com/parthmax2)
* ✉️ [Email](mailto:pathaksaksham430@gmail.com)

---

<div align="center">

⭐ *Star the repo* if you love it!
💡 *Built with ❤️ and Python by [Parthmax](https://github.com/parthmax2)*

</div>

