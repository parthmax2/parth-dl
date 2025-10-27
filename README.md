# parth-dl

**Instagram Media Downloader for Developers** — Download reels, posts, and profile pictures. Public content only. Zero dependencies.

[![Python Version](https://img.shields.io/badge/python-3.7+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Code Style](https://img.shields.io/badge/code%20style-clean-black.svg)]()

> Built by [@parthmax_](https://instagram.com/parthmax_) • Zero bloat, pure Python stdlib

---

## 🔥 Why parth-dl?

Most Instagram downloaders are **bloated**, **outdated**, or **require authentication**. This one doesn't.

- ✅ **Reels with audio** — Guaranteed combined streams
- ✅ **Posts (images/videos)** — Carousel support included
- ✅ **Profile pictures** — High-resolution extraction
- ✅ **Zero dependencies** — Pure Python stdlib (no pip hell)
- ✅ **Rate limiting** — Built-in protection against IP bans
- ✅ **Retry logic** — Exponential backoff on failures
- ✅ **Public only** — No login required

---

## ⚡ Installation

### From Source
```bash
git clone https://github.com/parthmax2/parth-dl.git
cd parth-dl
pip install -e .
```

### From PyPI (soon)
```bash
pip install parth-dl
```

---

## 🚀 Usage

### CLI

```bash
# Download a reel
parth-dl https://www.instagram.com/reel/ABC123/

# Download a post
parth-dl https://www.instagram.com/p/ABC123/

# Download profile picture
parth-dl https://www.instagram.com/username/

# Custom output
parth-dl https://www.instagram.com/reel/ABC123/ -o my_video.mp4

# List formats
parth-dl https://www.instagram.com/reel/ABC123/ --list-formats

# Verbose mode
parth-dl https://www.instagram.com/reel/ABC123/ -v
```

### Python API

```python
from parth_dl import InstagramDownloader

# Initialize
dl = InstagramDownloader(verbose=True)

# Download
dl.download('https://www.instagram.com/reel/ABC123/')

# Get metadata
info = dl.get_info('https://www.instagram.com/reel/ABC123/')
print(info)
```

**Quick function:**
```python
from parth_dl import download
download('https://www.instagram.com/reel/ABC123/')
```

---

## 🛠️ Architecture

```
parth-dl/
├── parth_dl/
│   ├── __init__.py      # Package entry + exports
│   ├── core.py          # Main orchestrator
│   ├── extractors.py    # API/GraphQL/Embed/Page extractors
│   ├── utils.py         # Security, retry, rate-limit
│   └── cli.py           # CLI interface
├── setup.py
├── README.md
└── requirements.txt     # (Empty — zero deps!)
```

**Key Features:**
- **4 extraction methods** with intelligent fallback
- **Token bucket rate limiter** (30 req/60s)
- **Exponential backoff** with jitter
- **URL validation** to prevent injection
- **Filename sanitization** for safe I/O

---

## 🔒 Security

- **No external dependencies** → No supply chain attacks
- **URL validation** → Prevents injection
- **Rate limiting** → Avoids IP bans
- **Retry logic** → Handles transient failures
- **Timeout controls** → No hanging requests

---

## ⚠️ Disclaimer

**For educational and personal use only.**

This tool may violate Instagram's Terms of Service. By using it, you accept full responsibility for:
- Compliance with Instagram ToS
- Copyright and intellectual property laws
- Ethical usage

Only download content you have permission to use. Respect creators' rights.

---

## 🤝 Contributing

PRs welcome! Follow these steps:

1. Fork the repo
2. Create a feature branch (`git checkout -b feature/xyz`)
3. Commit changes (`git commit -m 'Add xyz'`)
4. Push to branch (`git push origin feature/xyz`)
5. Open a PR

---

## 📝 License

MIT License — See [LICENSE](LICENSE) for details.

**Provided "as is" without warranty.** Instagram may change APIs anytime. Not responsible for misuse.

---

## 📬 Connect

- **Author:** Saksham Pathak (Parthmax)
- **Instagram:** [@parthmax_](https://instagram.com/parthmax_)
- **LinkedIn:** [Saksham Pathak](https://linkedin.com/in/sakshampathak)
- **Hugging Face:** [parthmax](https://huggingface.co/parthmax)
- **Email:** pathaksaksham430@gmail.com

---

<div align="center">
  
**Built with ❤️ by Parthmax**

[⭐ Star this repo](https://github.com/parthmax2/parth-dl) if you found it useful!

</div>