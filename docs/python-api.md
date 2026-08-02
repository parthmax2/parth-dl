# Python Package Usage - Instagram Downloader API

Use `parth-dl` as a lightweight Python Instagram downloader package when you want to
download public reels, posts, carousels, or profile pictures from your own Python code.
The package has zero runtime dependencies and exposes both quick helper functions and a
reusable downloader class.

## Install

```bash
pip install parth-dl
```

Requires Python 3.9 or newer.

## Quick Start

```python
from parth_dl import download, get_info

url = "https://www.instagram.com/reel/Cxyz123AbCd/"

path = download(url)
info = get_info(url)

print(path)
print(info["title"])
```

`download()` saves media to the current working directory by default. For a single reel
or image it returns one string path. For a carousel it returns a list of string paths.
If every output file already exists and overwrite is disabled, it returns an empty list.

## Download To A Folder

```python
from parth_dl import download

files = download(
    "https://www.instagram.com/p/Cxyz123AbCd/",
    output_path="downloads/instagram",
)

print(files)
```

`output_path` is treated as a directory when it exists as a directory, ends with a path
separator, or has no file extension. Missing folders are created automatically.

## Download To An Exact Filename

```python
from parth_dl import download

path = download(
    "https://www.instagram.com/reel/Cxyz123AbCd/",
    output_path="clips/my-reel.mp4",
)
```

For carousels written to an explicit filename, parth-dl indexes the children:
`post.jpg` becomes `post_01.jpg`, `post_02.jpg`, and so on.

## Choose Quality

```python
download(url, quality="best")   # default, highest available rendition
download(url, quality="worst")  # smallest available rendition
```

Instagram does not always expose many renditions to logged-out clients. When only one
format is available, `best` and `worst` may resolve to the same file.

## Read Metadata Without Downloading

```python
from parth_dl import get_info

info = get_info("https://www.instagram.com/reel/Cxyz123AbCd/")

print(info["id"])
print(info["type"])
print(info["uploader"])
print(info["entries"][0]["formats"][0]["url"])
```

The returned dictionary is documented in [Metadata Schema](schema.md).

## Reuse A Downloader Instance

Use `InstagramDownloader` for batches, apps, workers, or services. Reusing one instance
keeps one rate limiter and one configuration for many URLs.

```python
from parth_dl import InstagramDownloader

downloader = InstagramDownloader(
    verbose=False,
    rate_limit=True,
    quiet=True,
    overwrite=False,
    caption_max_length=None,  # full caption in title + caption field
)

urls = [
    "https://www.instagram.com/reel/Cxyz123AbCd/",
    "https://www.instagram.com/p/ABC123/",
]

for url in urls:
    try:
        print(downloader.download(url, output_path="downloads/"))
    except Exception as exc:
        print(f"failed: {url}: {exc}")
```

## Progress Hook

Pass `progress_hook` when you want progress updates in your app, bot, queue worker, or
desktop UI.

```python
from parth_dl import InstagramDownloader


def on_progress(downloaded_bytes, total_bytes):
    if total_bytes:
        percent = downloaded_bytes / total_bytes * 100
        print(f"{percent:.1f}%")
    else:
        print(f"{downloaded_bytes} bytes")


downloader = InstagramDownloader(
    quiet=True,
    progress_hook=on_progress,
)

downloader.download("https://www.instagram.com/reel/Cxyz123AbCd/")
```

## Error Handling

Every public exception inherits from `DownloadError`.

```python
from parth_dl import (
    DownloadError,
    NetworkError,
    RateLimitError,
    ValidationError,
    download,
)

try:
    download("https://www.instagram.com/reel/Cxyz123AbCd/")
except ValidationError:
    print("Not a supported Instagram URL")
except RateLimitError:
    print("Instagram is throttling requests; wait and retry later")
except NetworkError:
    print("Network or CDN transfer failed after retries")
except DownloadError as exc:
    print(f"Download failed: {exc}")
```

Catch the most specific exception first. `ValidationError`, `RateLimitError`, and
`NetworkError` are all subclasses of `DownloadError`.

## Background Worker Example

Downloads are blocking, so web apps should run them in a worker thread, task queue, or
background job.

```python
from concurrent.futures import ThreadPoolExecutor

from parth_dl import DownloadError, InstagramDownloader

pool = ThreadPoolExecutor(max_workers=2)
downloader = InstagramDownloader(quiet=True)


def run_download(url):
    try:
        return {"ok": True, "files": downloader.download(url, output_path="downloads/")}
    except DownloadError as exc:
        return {"ok": False, "error": str(exc)}


future = pool.submit(run_download, "https://www.instagram.com/reel/Cxyz123AbCd/")
print(future.result())
```

If you need a ready-made local queue and JSON API, use `parth-dl serve` and read
[Local HTTP API Usage](http-api.md).

## Supported URLs

| Content | Python package support |
|---|---|
| Public reels | Supported |
| Public posts | Supported |
| Public carousels | Supported |
| Public profile pictures | Supported |
| Private accounts/posts | Not supported |
| Stories/highlights | Not supported |
| Login-only links | Limited by Instagram's logged-out response |

## Important Notes

- parth-dl does not log in and does not bypass Instagram access controls.
- Some public-looking links still return a login wall to logged-out clients.
- Keep rate limiting enabled for production usage.
- Direct CDN URLs returned in metadata can expire; download soon after extraction.
- Use the [Metadata Schema](schema.md) instead of depending on undocumented fields.
