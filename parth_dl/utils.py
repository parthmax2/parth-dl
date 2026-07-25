"""
Utility functions: retry logic, rate limiting, error handling
Security-focused with yt-dlp-inspired reliability
"""

import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
from functools import wraps
from pathlib import Path
from typing import Any, Callable


# Custom Exceptions
class DownloadError(Exception):
    """Base exception for download errors"""
    pass


class RateLimitError(DownloadError):
    """Raised when rate limited by Instagram"""
    pass


class NetworkError(DownloadError):
    """Raised on network failures"""
    pass


class ValidationError(DownloadError):
    """Raised on invalid input"""
    pass


class ExpiredMediaError(DownloadError):
    """Raised when an extracted CDN URL has expired and must be refreshed"""
    pass


# Exit codes (used by the CLI so callers can react to failure kinds)
EXIT_OK = 0
EXIT_DOWNLOAD_ERROR = 1
EXIT_USAGE = 2
EXIT_NETWORK_ERROR = 3
EXIT_RATE_LIMITED = 4
EXIT_VALIDATION_ERROR = 5
EXIT_INTERRUPTED = 130


# Console output: legacy Windows consoles are cp1252 and cannot encode the
# box-drawing / check / emoji characters, so fall back to ASCII equivalents.
def supports_unicode(stream=None):
    """Check whether the stream can encode the symbols we want to print"""
    stream = stream or sys.stdout
    encoding = getattr(stream, 'encoding', None)
    if not encoding:
        return False
    try:
        '█░✓✗⚠🔊'.encode(encoding)
        return True
    except (UnicodeEncodeError, LookupError):
        return False


_UNICODE_SYMBOLS = {
    'ok': '✓', 'fail': '✗', 'warn': '⚠',
    'audio': '🔊', 'muted': '🔇',
    'bar_full': '█', 'bar_empty': '░',
    'step': '◆', 'line': '─',
    'tl': '╔', 'tr': '╗', 'bl': '╚', 'br': '╝', 'h': '═', 'v': '║',
}

_ASCII_SYMBOLS = {
    'ok': '+', 'fail': 'x', 'warn': '!',
    'audio': '+', 'muted': '-',
    'bar_full': '#', 'bar_empty': '-',
    'step': '>', 'line': '-',
    'tl': '+', 'tr': '+', 'bl': '+', 'br': '+', 'h': '=', 'v': '|',
}


def symbols(stream=None):
    """Return the symbol table appropriate for the given output stream"""
    return _UNICODE_SYMBOLS if supports_unicode(stream) else _ASCII_SYMBOLS


def supports_color(stream=None):
    """Return whether ANSI styling is appropriate for this terminal."""
    stream = stream or sys.stdout
    if os.environ.get('NO_COLOR') is not None:
        return False
    if not hasattr(stream, 'isatty') or not stream.isatty():
        return False
    if os.environ.get('TERM') == 'dumb':
        return False
    if os.name == 'nt':
        return bool(
            os.environ.get('WT_SESSION')
            or os.environ.get('TERM_PROGRAM')
            or os.environ.get('ANSICON')
        )
    return True


_ANSI = {
    'reset': '\033[0m',
    'bold': '\033[1m',
    'dim': '\033[2m',
    'purple': '\033[38;5;183m',
    'blue': '\033[38;5;117m',
    'green': '\033[38;5;77m',
    'orange': '\033[38;5;215m',
    'red': '\033[38;5;203m',
    'track': '\033[38;5;238m',
}


def style(text, *names, stream=None):
    """Apply ANSI styles only when the destination supports them."""
    if not supports_color(stream):
        return str(text)
    prefix = ''.join(_ANSI[name] for name in names)
    return f"{prefix}{text}{_ANSI['reset']}"


def supports_hyperlinks(stream=None):
    """
    Check whether the terminal understands OSC 8 hyperlink escapes.

    Emitting them into a terminal that does not would dump the raw escape bytes
    on screen, so this errs on the side of saying no.
    """
    stream = stream or sys.stdout

    if os.environ.get('NO_HYPERLINKS'):
        return False

    if not hasattr(stream, 'isatty') or not stream.isatty():
        return False

    # The legacy Windows console (conhost) has no OSC 8 support. Windows
    # Terminal and the VS Code terminal do, and both advertise themselves.
    if os.name == 'nt':
        return bool(os.environ.get('WT_SESSION') or os.environ.get('TERM_PROGRAM'))

    return True


def file_uri(path):
    """Convert a filesystem path into a clickable file:// URI"""
    return Path(path).resolve().as_uri()


def hyperlink(label, url, stream=None):
    """
    Render `label` as a clickable link pointing at `url`.

    Terminals without OSC 8 support get the bare URL instead - it still carries
    the full path, and most of them auto-linkify it, so the result stays
    clickable either way.
    """
    if supports_hyperlinks(stream):
        return f'\033]8;;{url}\033\\{label}\033]8;;\033\\'
    return url


def harden_stdio():
    """
    Make stdout/stderr never raise UnicodeEncodeError.
    Belt-and-braces on top of the ASCII symbol fallback: any stray non-encodable
    character (e.g. emoji inside an Instagram caption) is replaced, not fatal.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, 'reconfigure', None)
        if reconfigure:
            try:
                reconfigure(errors='replace')
            except (ValueError, OSError):
                pass


class RateLimiter:
    """Sliding-window rate limiter to prevent IP bans"""

    def __init__(self, max_requests=30, time_window=60):
        """
        Args:
            max_requests: Maximum requests allowed
            time_window: Time window in seconds
        """
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = []
        self._lock = threading.Lock()

    def _prune(self, now):
        self.requests = [t for t in self.requests if now - t < self.time_window]

    def wait_if_needed(self):
        """Block if rate limit would be exceeded"""
        # One limiter is shared by every extractor and transfer in a session.
        # Holding the lock while waiting prevents a burst of worker threads from
        # all observing the same free slot and exceeding the configured window.
        with self._lock:
            now = time.time()
            self._prune(now)

            if len(self.requests) >= self.max_requests:
                oldest_request = min(self.requests)
                wait_time = self.time_window - (now - oldest_request)

                if wait_time > 0:
                    time.sleep(wait_time + 0.1)  # Small buffer

                now = time.time()
                self._prune(now)

            self.requests.append(now)


class ExponentialBackoff:
    """Exponential backoff for retry logic"""

    def __init__(self, base_delay=1.0, max_delay=60.0, max_retries=3):
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.max_retries = max_retries

    def get_delay(self, attempt):
        """Calculate delay for given attempt (0-indexed)"""
        delay = min(self.base_delay * (2 ** attempt), self.max_delay)
        # Add jitter to prevent thundering herd
        import random
        jitter = random.uniform(0, delay * 0.1)
        return delay + jitter


# Transient failures worth another attempt. urllib raises URLError/HTTPError
# (subclasses of OSError, not of ConnectionError), so they must be listed
# explicitly or a mid-transfer connection reset would never be retried.
RETRYABLE_EXCEPTIONS = (
    NetworkError,
    ConnectionError,
    TimeoutError,
    urllib.error.URLError,
    OSError,
)


def retry_on_failure(max_retries=3, backoff=None):
    """
    Decorator for retrying failed operations with exponential backoff
    Inspired by yt-dlp's retry mechanism
    """
    if backoff is None:
        backoff = ExponentialBackoff(max_retries=max_retries)

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            last_exception = None

            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)

                except (RateLimitError, ValidationError):
                    # Retrying these only makes things worse; fail fast
                    raise

                # NetworkError subclasses DownloadError, so this clause must come
                # first - otherwise the fail-fast clause below would swallow it.
                except RETRYABLE_EXCEPTIONS as e:
                    last_exception = e

                    if attempt < max_retries - 1:
                        time.sleep(backoff.get_delay(attempt))
                    else:
                        raise NetworkError(f"Failed after {max_retries} attempts: {e}")

                except DownloadError:
                    # Content is private/deleted/unsupported - a retry can't help
                    raise

            raise NetworkError(f"Failed after {max_retries} attempts: {last_exception}")

        return wrapper
    return decorator


# Reserved device names on Windows - a file cannot be created with these stems
_WINDOWS_RESERVED = {
    'CON', 'PRN', 'AUX', 'NUL',
    *(f'COM{i}' for i in range(1, 10)),
    *(f'LPT{i}' for i in range(1, 10)),
}


def sanitize_filename(filename, max_length=100):
    """
    Sanitize filename for safe filesystem operations
    Security: Prevent directory traversal and invalid characters
    """
    if not filename:
        return "untitled"

    # Remove path separators and dangerous characters
    filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', filename)

    # Drop characters the filesystem accepts but that make filenames unusable
    # (emoji and other non-BMP symbols commonly found in captions)
    filename = ''.join(c for c in filename if c.isprintable() and ord(c) < 0x1F000)

    # Remove leading/trailing spaces and dots
    filename = filename.strip('. ')

    # Replace multiple spaces/dashes with single
    filename = re.sub(r'[\s-]+', '_', filename)
    filename = filename.strip('_')

    # Limit length
    if len(filename) > max_length:
        filename = filename[:max_length].rstrip('_')

    # Windows reserved device names cannot be used as a filename stem
    if filename.upper() in _WINDOWS_RESERVED:
        filename = f"{filename}_"

    # Ensure not empty after sanitization
    return filename or "untitled"


def validate_url(url):
    """
    Validate Instagram URL for security
    Prevents injection attacks and malformed URLs
    """
    if not url or not isinstance(url, str):
        raise ValidationError("URL must be a non-empty string")

    # Check for valid Instagram domain
    instagram_pattern = r'^https?://(?:www\.)?instagram\.com/'
    if not re.match(instagram_pattern, url, re.IGNORECASE):
        raise ValidationError("URL must be from instagram.com")

    return True


# Hosts Instagram serves media from. Extracted URLs come from Instagram's own
# JSON, but they are still attacker-influenced input, so the download path must
# not be talked into fetching file:// or an arbitrary third-party host.
_MEDIA_HOST_PATTERN = re.compile(
    r'^(?:[\w.-]+\.)?(?:cdninstagram\.com|fbcdn\.net|instagram\.com)$',
    re.IGNORECASE,
)


def validate_media_url(url):
    """Validate a CDN media URL before fetching it"""
    import urllib.parse

    if not url or not isinstance(url, str):
        raise ValidationError("Media URL is missing")

    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != 'https':
        raise ValidationError(f"Refusing to download over '{parsed.scheme or 'no'}' scheme")

    if not _MEDIA_HOST_PATTERN.match(parsed.hostname or ''):
        raise ValidationError(f"Refusing to download from unexpected host: {parsed.hostname}")

    return True


_EXTENSIONS = {
    'video': '.mp4',
    'image': '.jpg',
}

_KNOWN_EXTENSIONS = {'.mp4', '.mov', '.webm', '.jpg', '.jpeg', '.png', '.webp', '.heic'}


def guess_extension(url, media_kind='video'):
    """Derive the file extension from the CDN URL, falling back on media kind"""
    import urllib.parse

    path = urllib.parse.urlparse(url or '').path
    ext = os.path.splitext(path)[1].lower()

    if ext in _KNOWN_EXTENSIONS:
        return ext

    return _EXTENSIONS.get(media_kind, '.bin')


def select_format(formats, quality='best'):
    """
    Pick a format by quality preference.

    Dimensions are treated as 0 when absent OR null - Instagram's GraphQL
    responses do include `"width": null`, which `.get(key, 0)` would happily
    return as None.
    """
    formats = [f for f in formats if f.get('url')]
    if not formats:
        return None

    def area(fmt):
        width = fmt.get('width') or 0
        height = fmt.get('height') or 0
        return (width * height, height)

    chooser = max if quality == 'best' else min
    return chooser(formats, key=area)


def finalize_info(info):
    """
    Populate the legacy top-level `formats` / `images` keys from `entries`,
    so library callers written against the old shape keep working.
    """
    entries = info.get('entries') or []

    video_entries = [e for e in entries if e['kind'] == 'video']
    image_entries = [e for e in entries if e['kind'] == 'image']

    info['formats'] = video_entries[0]['formats'] if video_entries else []
    info['images'] = [
        fmt for entry in image_entries
        for fmt in [select_format(entry['formats'], 'best')] if fmt
    ]

    return info


def _walk_mp4_boxes(data):
    """Yield (box_type, payload) for the boxes directly inside `data`"""
    import struct

    offset = 0
    while offset + 8 <= len(data):
        size, box_type = struct.unpack('>I4s', data[offset:offset + 8])
        header = 8

        if size == 1:  # 64-bit extended size
            if offset + 16 > len(data):
                return
            size = struct.unpack('>Q', data[offset + 8:offset + 16])[0]
            header = 16
        elif size == 0:  # box runs to end of file
            size = len(data) - offset

        if size < header or offset + size > len(data):
            return

        yield box_type, data[offset + header:offset + size]
        offset += size


def read_mp4_dimensions(path):
    """
    Read the true display dimensions from an MP4's video track header.

    Instagram's metadata reports the dimensions of the *original* upload, while
    the file it serves a logged-out client is often a smaller transcode - so the
    only trustworthy source for what was actually downloaded is the file itself.

    Returns (width, height), or None if the file isn't a parseable MP4.
    """
    import struct

    try:
        with open(path, 'rb') as f:
            data = f.read()
    except OSError:
        return None

    for box_type, payload in _walk_mp4_boxes(data):
        if box_type != b'moov':
            continue

        for trak_type, trak in _walk_mp4_boxes(payload):
            if trak_type != b'trak':
                continue

            for tkhd_type, tkhd in _walk_mp4_boxes(trak):
                # width/height are the final two 16.16 fixed-point fields of tkhd
                if tkhd_type != b'tkhd' or len(tkhd) < 8:
                    continue

                width, height = struct.unpack('>II', tkhd[-8:])
                width, height = width >> 16, height >> 16

                # Audio tracks carry 0x0; the first non-zero trak is the video
                if width and height:
                    return width, height

    return None


def format_size(size_bytes):
    """Format bytes into human-readable size"""
    size_bytes = float(size_bytes or 0)
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} TB"


def format_duration(seconds):
    """Format seconds into HH:MM:SS"""
    if not seconds:
        return "Unknown"

    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)

    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    else:
        return f"{minutes:02d}:{secs:02d}"


def extract_instagram_id(url):
    """
    Extract Instagram post/reel shortcode from URL
    Supports various URL formats
    """
    try:
        parsed = urllib.parse.urlparse(url)
    except (TypeError, ValueError):
        return None

    if (parsed.hostname or '').lower() not in ('instagram.com', 'www.instagram.com'):
        return None

    parts = [urllib.parse.unquote(part) for part in parsed.path.split('/') if part]
    if len(parts) >= 2 and parts[0].lower() in ('p', 'tv', 'reel', 'reels'):
        shortcode = parts[1]
    elif len(parts) >= 3 and parts[1].lower() in ('p', 'reel', 'reels'):
        shortcode = parts[2]
    else:
        # Stories are intentionally not treated as posts. Their numeric media
        # IDs are not post shortcodes and routing them through /p/ can fetch the
        # wrong resource.
        return None

    return shortcode if re.fullmatch(r'[A-Za-z0-9_-]+', shortcode) else None


def extract_username(url):
    """Extract Instagram username from URL"""
    try:
        parsed = urllib.parse.urlparse(url)
    except (TypeError, ValueError):
        return None

    if (parsed.hostname or '').lower() not in ('instagram.com', 'www.instagram.com'):
        return None

    parts = [urllib.parse.unquote(part) for part in parsed.path.split('/') if part]
    if len(parts) != 1:
        return None

    username = parts[0][1:] if parts[0].startswith('@') else parts[0]
    if not re.fullmatch(r'[A-Za-z0-9_.]+', username):
        return None

    reserved = {'p', 'reel', 'reels', 'tv', 'stories', 'explore', 'accounts'}
    return username if username.lower() not in reserved else None


def is_profile_url(url):
    """Check if URL is a profile URL (for DP download)"""
    return extract_username(url) is not None


def is_media_url(url):
    """Check if URL is a media URL (post/reel)"""
    return extract_instagram_id(url) is not None


class ProgressBar:
    """Compact two-line progress display with a plain-terminal fallback."""

    RENDER_INTERVAL = 0.1  # seconds between redraws

    def __init__(self, total_size, desc="Downloading", initial=0, stream=None):
        self.total_size = total_size
        self.desc = desc
        self.downloaded = initial
        self.resumed_at = initial
        self.start_time = time.time()
        self.stream = stream or sys.stdout
        self.symbols = symbols(self.stream)
        self.enabled = self.stream.isatty()
        self.color = supports_color(self.stream)
        self._last_render = 0.0
        self._rendered = False

    def update(self, chunk_size):
        """Update progress, redrawing at most every RENDER_INTERVAL"""
        self.downloaded += chunk_size

        now = time.time()
        if now - self._last_render < self.RENDER_INTERVAL:
            return

        self._last_render = now
        self._render()

    def _render(self):
        if not self.enabled or self.total_size <= 0:
            return

        fraction = min(self.downloaded / self.total_size, 1.0)
        percent = fraction * 100

        elapsed = time.time() - self.start_time
        speed = (self.downloaded - self.resumed_at) / elapsed if elapsed > 0 else 0
        remaining = self.total_size - self.downloaded
        eta = format_duration(remaining / speed) if speed > 0 and remaining > 0 else "00:00"

        try:
            import shutil
            columns = shutil.get_terminal_size((80, 20)).columns
        except OSError:
            columns = 80
        bar_length = max(18, min(54, columns - 8))
        filled = int(bar_length * fraction)
        full = self.symbols['bar_full'] * filled
        empty = self.symbols['bar_empty'] * (bar_length - filled)
        bar = style(full, 'green', stream=self.stream) + style(
            empty, 'track', stream=self.stream,
        )
        metrics = (
            f"{format_size(self.downloaded)} / {format_size(self.total_size)}"
            f"  ·  {format_size(speed)}/s"
            f"  ·  {eta} left"
        )

        if self.color:
            if self._rendered:
                print('\033[1A\r', end='', file=self.stream)
            print(f"\r\033[2K  {bar}", file=self.stream)
            print(
                f"\r\033[2K  {style(metrics, 'dim', stream=self.stream)}",
                end='', flush=True, file=self.stream,
            )
            self._rendered = True
            return

        plain_bar = full + empty
        print(
            f'\r{self.desc}: |{plain_bar}| {percent:5.1f}% {metrics}',
            end='', flush=True, file=self.stream,
        )

    def finish(self):
        """Complete the progress bar"""
        if not self.enabled or self.total_size <= 0:
            return
        self._render()
        print(file=self.stream)  # New line
