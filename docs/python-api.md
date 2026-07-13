# Python API

```bash
pip install parth-dl
```

## Quick functions

```python
from parth_dl import download, get_info

path = download("https://www.instagram.com/reel/Cxyz123AbCd/")
info = get_info("https://www.instagram.com/reel/Cxyz123AbCd/")
```

### `download(url, output_path=None, quality='best', verbose=False)`

Returns a **string path** for a single item, or a **list of paths** for a carousel.
Returns `[]` if every file already existed and was skipped.

```python
download(url)                                  # -> "parthmax_-Cxyz.mp4", into the cwd
download(url, output_path="clips/")            # into a directory (created if missing)
download(url, output_path="clip.mp4")          # to an exact filename
download(url, quality="worst")                 # smallest rendition
```

`output_path` is treated as a directory when it exists as one, ends in a separator,
or has no file extension. For a carousel written to an explicit filename, the children
are indexed: `pic.jpg` → `pic_01.jpg`, `pic_02.jpg`.

### `get_info(url, verbose=False)`

Returns the metadata dict without downloading. See **[schema.md](schema.md)** for every field.

## The class

Use `InstagramDownloader` when you need to configure behaviour or reuse a session
across many URLs (it keeps one rate limiter, which is what you want for a batch).

```python
from parth_dl import InstagramDownloader

dl = InstagramDownloader(
    verbose=False,       # log extraction steps
    rate_limit=True,     # 30 req/min sliding window. Leave this on.
    quiet=False,         # suppress progress output
    overwrite=False,     # False skips files that already exist
    progress_hook=None,  # callable(downloaded_bytes, total_bytes)
)

dl.get_info(url)         # metadata only
dl.download(url)         # fetch
dl.list_formats(url)     # print the available renditions
```

### Progress

`progress_hook` is called with `(downloaded_bytes, total_bytes)` as bytes arrive.
`total_bytes` is `0` when the CDN sends no `Content-Length` — guard for it:

```python
def on_progress(downloaded, total):
    if total:
        print(f"{downloaded / total:.0%}")

InstagramDownloader(progress_hook=on_progress, quiet=True).download(url)
```

## Errors

Every failure is a subclass of `DownloadError`, so one `except` catches everything:

```python
from parth_dl import DownloadError, NetworkError, RateLimitError, ValidationError

try:
    download(url)
except ValidationError:   # not an instagram.com URL, or malformed
    ...
except RateLimitError:    # Instagram is throttling this IP - back off
    ...
except NetworkError:      # transfer failed after retries
    ...
except DownloadError:     # private, deleted, or unsupported content
    ...
```

`ValidationError`, `RateLimitError` and `NetworkError` all inherit from `DownloadError`,
so **order your `except` clauses most-specific first.**

## Recipe: a Flask endpoint

```python
from flask import Flask, jsonify, request
from parth_dl import DownloadError, InstagramDownloader

app = Flask(__name__)
dl = InstagramDownloader(quiet=True)   # one shared rate limiter

@app.post("/info")
def info():
    try:
        return jsonify(dl.get_info(request.json["url"]))
    except DownloadError as e:
        return jsonify(error=str(e)), 400
```

Downloads are blocking and can take a while, so run them on a worker (Celery, RQ, a
thread) rather than inside the request. `parth_dl.server` does exactly this with a
thread pool if you want a reference implementation.

## Notes

- **Public content only.** Stories, highlights and private accounts need
  authentication and are not supported.
- Downloads are **resumable**: an interrupted transfer is left as a `.part` file and
  picked up on the next call. A file only gets its final name once every byte has
  arrived, so a partial download can never be mistaken for a complete one.
- Keep `rate_limit=True`. It is what stops Instagram blocking your IP.
