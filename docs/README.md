# parth-dl Documentation

Start here if you want to use, integrate, or contribute to `parth-dl`, a lightweight
Python Instagram video downloader for public reels, posts, carousels, and profile
pictures.

## Choose Your Path

| I want to... | Read |
|---|---|
| Use the terminal command | [CLI Reference](cli.md) |
| Import `parth-dl` in Python | [Python Package Usage](python-api.md) |
| Use it from Node, Go, PHP, Rust, a browser, or another app | [Local HTTP API Usage](http-api.md) |
| Use the local browser interface | [Web UI Usage](web-ui.md) |
| Understand the JSON response | [Metadata schema](schema.md) |
| Copy an integration example | [Recipes](recipes.md) |
| Work on the codebase | [Development guide](development.md) |

## Fastest Working Examples

CLI:

```bash
parth-dl https://www.instagram.com/reel/Cxyz123AbCd/
```

Python:

```python
from parth_dl import download

download("https://www.instagram.com/reel/Cxyz123AbCd/", output_path="downloads/")
```

HTTP:

```bash
parth-dl serve
curl -X POST http://127.0.0.1:8000/api/info \
  -H "Content-Type: application/json" \
  -d "{\"url\":\"https://www.instagram.com/reel/Cxyz123AbCd/\"}"
```

Web UI:

```bash
parth-dl serve
# open http://127.0.0.1:8000
```

## Important Rules

- Public content only.
- No cookies are required or supported.
- Keep rate limiting enabled for real usage.
- Treat direct CDN URLs as short-lived.
- Branch on exit codes, Python exceptions, or HTTP statuses instead of parsing messages.

## Need Help Debugging?

Start with:

```bash
parth-dl -v --json URL
```

Then read [development.md#debugging-instagram-extraction](development.md#debugging-instagram-extraction).
