"""
Core downloader class - orchestrates extraction and downloading
"""

import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from .extractors import MediaExtractor, ProfilePictureExtractor
from .utils import (
    DownloadError,
    ExpiredMediaError,
    NetworkError,
    ProgressBar,
    RateLimiter,
    RateLimitError,
    ValidationError,
    extract_instagram_id,
    file_uri,
    format_size,
    guess_extension,
    hyperlink,
    is_media_url,
    is_profile_url,
    read_mp4_dimensions,
    retry_on_failure,
    sanitize_filename,
    select_format,
    style,
    symbols,
    validate_media_url,
    validate_url,
)


class ResumeRejectedError(DownloadError):
    """The server rejected a byte-range resume request."""


class ValidatingRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Revalidate every redirect instead of trusting only the initial CDN URL."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_media_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OUTPUT_LOCKS = {}
_OUTPUT_LOCKS_GUARD = threading.Lock()


def _output_lock(path):
    """Return a process-wide lock for a destination path."""
    key = str(Path(path).resolve())
    with _OUTPUT_LOCKS_GUARD:
        return _OUTPUT_LOCKS.setdefault(key, threading.Lock())


class InstagramDownloader:
    """
    Main Instagram downloader class
    Supports: reels, posts (single/carousel images/videos), profile pictures
    Public accounts only - no authentication required
    """

    BASE_HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': '*/*',
        'Referer': 'https://www.instagram.com/',
    }

    CHUNK_SIZE = 65536

    def __init__(self, verbose=False, rate_limit=True, quiet=False, overwrite=False,
                 progress_hook=None, rate_limiter=None):
        """
        Initialize downloader

        Args:
            verbose: Enable verbose logging
            rate_limit: Enable rate limiting (recommended)
            quiet: Suppress progress output
            overwrite: Overwrite existing files instead of skipping them
            progress_hook: Optional callable(downloaded_bytes, total_bytes) invoked
                as the transfer advances. Used by the web UI to report progress;
                `total_bytes` is 0 when the server sends no Content-Length.
        """
        self.verbose = verbose
        self.quiet = quiet
        self.overwrite = overwrite
        self.progress_hook = progress_hook
        self.progress_item_index = 1
        self.progress_item_count = 1
        self.last_skipped_files = []
        self.last_info = None
        self.rate_limiter = (
            rate_limiter if rate_limiter is not None
            else RateLimiter(max_requests=30, time_window=60) if rate_limit
            else None
        )
        self.sym = symbols()

        # Initialize extractors
        self.media_extractor = MediaExtractor(
            verbose=verbose, rate_limiter=self.rate_limiter,
        )
        self.profile_extractor = ProfilePictureExtractor(
            verbose=verbose, rate_limiter=self.rate_limiter,
        )

    def log(self, message):
        """Print verbose log messages"""
        if self.verbose:
            print(f"[parth-dl] {message}", file=sys.stderr)

    def out(self, message=''):
        """Print user-facing progress output unless quiet"""
        if not self.quiet:
            print(message)

    def _stage(self, label, state=None):
        """Render one compact workflow row."""
        if self.quiet:
            return
        marker = style(self.sym['step'], 'orange')
        suffix = f"  {style(state, 'green')}" if state else ''
        self.out(f"{marker} {label}{suffix}")

    def _result(self, label, path, details=None):
        """Render a saved/existing file as a concise clickable result."""
        marker = style(self.sym['ok'], 'green')
        target = hyperlink(str(path), file_uri(path))
        self.out(f"{marker} {label}  {style(target, 'blue')}")
        if details:
            self.out(f"  {style(' · '.join(details), 'dim')}")

    def get_info(self, url):
        """
        Get media information without downloading

        Args:
            url: Instagram URL (post, reel, or profile)

        Returns:
            Dictionary with media information
        """
        # Validate URL
        validate_url(url)

        # Media URLs are checked first: a profile match is the looser pattern,
        # so checking it first would misroute anything it happens to also match.
        if is_media_url(url):
            self.log("Detected media URL")
            return self.media_extractor.extract(url)
        elif is_profile_url(url):
            self.log("Detected profile URL")
            return self.profile_extractor.extract(url)
        else:
            raise DownloadError("Unsupported URL format. Use post/reel/profile URL.")

    def _open_url(self, url, headers):
        """Open a URL, mapping HTTP failures onto our exception hierarchy"""
        req = urllib.request.Request(url, headers=headers)

        try:
            opener = urllib.request.build_opener(ValidatingRedirectHandler())
            return opener.open(req, timeout=60)

        except urllib.error.HTTPError as e:
            if e.code in (403, 404, 410):
                raise ExpiredMediaError(
                    f"HTTP {e.code}: media URL is no longer valid (expired or removed)"
                )
            if e.code == 416:
                raise ResumeRejectedError("Server rejected the resume range")
            if e.code == 429:
                raise RateLimitError("Rate limited by Instagram. Please wait before retrying.")
            raise NetworkError(f"HTTP {e.code}: {e.reason}")

    @retry_on_failure(max_retries=5)
    def _download_file(self, url, output_path, show_progress=True):
        """
        Download a file to `output_path`, resuming an interrupted transfer.

        The bytes land in a sibling `.part` file and are only renamed into place
        once the full Content-Length has arrived, so an interrupted download can
        never be mistaken for a complete one.

        Args:
            url: Direct download URL
            output_path: Output file path
            show_progress: Show download progress
        """
        validate_media_url(url)

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        part_path = output_path.with_name(output_path.name + '.part')
        meta_path = output_path.with_name(output_path.name + '.part.json')

        with _output_lock(output_path):
            resume_from = part_path.stat().st_size if part_path.exists() else 0
            resume_meta = {}

            if resume_from:
                try:
                    resume_meta = json.loads(meta_path.read_text(encoding='utf-8'))
                except (OSError, ValueError, TypeError):
                    resume_meta = {}

                if resume_meta.get('url') != url:
                    self.log("Partial file belongs to another source; restarting")
                    part_path.unlink(missing_ok=True)
                    meta_path.unlink(missing_ok=True)
                    resume_from = 0

            if not resume_from:
                meta_path.unlink(missing_ok=True)

            headers = dict(self.BASE_HEADERS)
            if resume_from:
                headers['Range'] = f'bytes={resume_from}-'
                validator = resume_meta.get('etag') or resume_meta.get('last_modified')
                if validator:
                    headers['If-Range'] = validator
                self.log(f"Resuming from {format_size(resume_from)}")

            if self.rate_limiter:
                self.rate_limiter.wait_if_needed()

            try:
                response = self._open_url(url, headers)
            except ResumeRejectedError:
                if not resume_from:
                    raise
                self.log("Resume rejected, restarting download")
                part_path.unlink(missing_ok=True)
                meta_path.unlink(missing_ok=True)
                resume_from = 0
                if self.rate_limiter:
                    self.rate_limiter.wait_if_needed()
                response = self._open_url(url, dict(self.BASE_HEADERS))

            # A 206 is safe only when it begins at the exact byte we have.
            if resume_from and response.getcode() == 206:
                content_range = response.headers.get('Content-Range') or ''
                match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', content_range)
                expected_total = resume_meta.get('total_size')
                range_mismatch = (
                    not match
                    or int(match.group(1)) != resume_from
                    or (expected_total is not None
                        and int(match.group(3)) != expected_total)
                )
                if range_mismatch:
                    response.close()
                    self.log("Server returned a mismatched Content-Range; restarting")
                    part_path.unlink(missing_ok=True)
                    meta_path.unlink(missing_ok=True)
                    resume_from = 0
                    if self.rate_limiter:
                        self.rate_limiter.wait_if_needed()
                    response = self._open_url(url, dict(self.BASE_HEADERS))
            elif resume_from:
                # A server that ignores Range replies 200 and resends byte zero.
                self.log("Server ignored Range request, restarting from zero")
                resume_from = 0

            with response:
                try:
                    content_length = int(response.headers.get('Content-Length') or 0)
                except (TypeError, ValueError):
                    raise NetworkError("Server returned an invalid Content-Length")

                if content_length <= 0:
                    raise NetworkError(
                        "Server did not provide Content-Length; refusing an unverifiable transfer"
                    )

                content_type = (response.headers.get('Content-Type') or '').lower()
                if (content_type.startswith('text/')
                        or any(kind in content_type for kind in ('json', 'html', 'xml'))):
                    raise DownloadError(
                        f"Server returned non-media content ({content_type or 'unknown'})"
                    )

                if resume_from and response.getcode() == 206:
                    content_range = response.headers.get('Content-Range') or ''
                    match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', content_range)
                    total_size = int(match.group(3))
                    if int(match.group(2)) - resume_from + 1 != content_length:
                        raise NetworkError("Content-Range and Content-Length disagree")
                else:
                    total_size = content_length

                meta = {
                    'url': url,
                    'etag': response.headers.get('ETag'),
                    'last_modified': response.headers.get('Last-Modified'),
                    'total_size': total_size,
                }
                meta_path.write_text(json.dumps(meta), encoding='utf-8')

                progress = None
                if show_progress and not self.quiet:
                    progress = ProgressBar(total_size, initial=resume_from)

                mode = 'ab' if resume_from else 'wb'
                downloaded = resume_from
                with open(part_path, mode) as f:
                    while True:
                        chunk = response.read(self.CHUNK_SIZE)
                        if not chunk:
                            break

                        f.write(chunk)
                        downloaded += len(chunk)

                        if progress:
                            progress.update(len(chunk))
                        if self.progress_hook:
                            self.progress_hook(downloaded, total_size)

                if progress:
                    progress.finish()

            written = part_path.stat().st_size
            if written != total_size:
                raise NetworkError(
                    f"Incomplete download: got {format_size(written)} of {format_size(total_size)}"
                )

            os.replace(part_path, output_path)
            meta_path.unlink(missing_ok=True)
            self.log(f"Downloaded: {output_path} ({format_size(written)})")

            return output_path

    def _select_best_format(self, formats, quality='best'):
        """
        Select a format by quality preference, preferring formats that carry audio

        Args:
            formats: List of format dictionaries
            quality: 'best' or 'worst'

        Returns:
            Selected format dictionary
        """
        with_audio = [f for f in formats if f.get('has_audio')]
        return select_format(with_audio or formats, quality)

    def _build_path(self, info, entry, index, total, output_dir, output_path, fmt):
        """Work out where a single media entry should be written"""
        if output_path:
            output_path = Path(output_path)
            if total == 1:
                return output_path
            # A single -o name cannot hold N carousel children, so index it.
            # Use each child's real extension so mixed carousels do not save
            # JPEG bytes as .mp4 (or video bytes as .jpg).
            ext = guess_extension(fmt.get('url'), entry['kind'])
            return output_path.with_name(
                f"{output_path.stem}_{index:02d}{ext}"
            )

        uploader = sanitize_filename(info.get('uploader', 'unknown'))
        media_id = sanitize_filename(info.get('id', 'unknown'))
        ext = guess_extension(fmt.get('url'), entry['kind'])

        # For a profile picture the id *is* the username, so "user-user.jpg"
        stem = (f"{uploader}-profile" if info.get('type') == 'profile_picture'
                else f"{uploader}-{media_id}")

        suffix = f"_{index:02d}" if total > 1 else ""
        return Path(output_dir) / f"{stem}{suffix}{ext}"

    def _report_resolution(self, file_path, entry, fmt):
        """Return the real resolution when readable, otherwise Instagram's value."""
        claimed = (fmt.get('width'), fmt.get('height'))

        actual = read_mp4_dimensions(file_path) if entry['kind'] == 'video' else None
        if actual:
            if claimed != (None, None) and claimed != actual:
                self.log(f"Instagram reported {claimed[0]}x{claimed[1]} for the source upload")
            return actual
        if all(claimed):
            return claimed
        return None

    def download(self, url, output_path=None, quality='best', output_mode='auto',
                 info=None):
        """
        Download media from Instagram URL

        Args:
            url: Instagram URL (post, reel, or profile)
            output_path: Output file path, or a directory to write into
            quality: 'best' or 'worst'
            output_mode: 'file', 'directory', or 'auto' for legacy API calls
            info: Optional trusted metadata from a preceding get_info() call

        Returns:
            Path (or list of paths) to the downloaded file(s)
        """
        started_at = time.monotonic()
        if info is None:
            media_id = extract_instagram_id(url)
            if media_id:
                kind = 'reel' if re.search(r'/reels?/', url, re.IGNORECASE) else 'post'
                subject = f"{kind} {media_id}"
            else:
                subject = "Instagram link"
            self._stage(f"resolving {subject}", "done")
            info = self.get_info(url)
            self._stage("fetching media metadata", "done")
        self.last_info = info

        if not info or not info.get('entries'):
            raise DownloadError("No downloadable content found")

        if output_mode not in ('auto', 'file', 'directory'):
            raise ValidationError("output_mode must be 'auto', 'file', or 'directory'")

        # The CLI supplies an explicit mode for -o and -P. `auto` remains for
        # backwards-compatible Python API calls where output_path historically
        # accepted either a file or a directory.
        output_dir = os.getcwd()
        if output_path:
            candidate = Path(output_path)
            looks_like_dir = output_mode == 'directory' or (
                output_mode == 'auto' and (
                    candidate.is_dir()
                    or str(output_path).endswith(('/', '\\'))
                    or not candidate.suffix
                )
            )
            if looks_like_dir:
                candidate.mkdir(parents=True, exist_ok=True)
                output_dir, output_path = candidate, None

        entries = info['entries']
        total = len(entries)
        downloaded_files = []
        self.last_skipped_files = []
        skipped = 0

        for index, entry in enumerate(entries, 1):
            fmt = self._select_best_format(entry['formats'], quality)
            if not fmt:
                self.out(f"[{index}/{total}] {self.sym['warn']} no usable format, skipping")
                continue

            file_path = self._build_path(info, entry, index, total, output_dir, output_path, fmt)

            if file_path.exists() and not self.overwrite:
                details = [entry['kind'], 'already downloaded']
                if entry['kind'] == 'video' and fmt.get('has_audio'):
                    details.append('audio')
                self._result("exists", file_path, details)
                skipped += 1
                self.last_skipped_files.append(str(file_path))
                continue

            item = f" {index}/{total}" if total > 1 else ""
            self._stage(f"downloading {entry['kind']}{item}")

            self.progress_item_index = index
            self.progress_item_count = total

            try:
                self._download_file(fmt['url'], file_path, show_progress=(total == 1))
            except ExpiredMediaError:
                # CDN links are short-lived. Refresh metadata once and retry the
                # same carousel child instead of retrying a known-dead URL.
                self.log("Media URL expired; refreshing metadata")
                refreshed = self.get_info(url)
                refreshed_entries = refreshed.get('entries') or []
                if index > len(refreshed_entries):
                    raise DownloadError("Media changed while refreshing its download URL")
                refreshed_entry = refreshed_entries[index - 1]
                if refreshed_entry.get('kind') != entry.get('kind'):
                    raise DownloadError("Media changed type while refreshing its download URL")
                entry = refreshed_entry
                fmt = self._select_best_format(entry.get('formats') or [], quality)
                if not fmt:
                    raise DownloadError("No usable format after refreshing media metadata")
                self._download_file(fmt['url'], file_path, show_progress=(total == 1))
            downloaded_files.append(str(file_path))

            resolution = self._report_resolution(file_path, entry, fmt)
            details = [entry['kind']]
            if resolution:
                details.append(f"{resolution[0]}x{resolution[1]}")
            if entry['kind'] == 'video':
                details.append('audio' if fmt.get('has_audio') else 'no audio')
            self._result("saved", file_path, details)

        if not downloaded_files:
            if skipped:
                noun = 'file' if skipped == 1 else 'files'
                self.out()
                self.out(style(f"{skipped} {noun} already present", 'dim'))
                return []
            raise DownloadError("No downloadable content found")

        self.out()
        self.out(style(self.sym['line'] * 48, 'track'))
        elapsed = time.monotonic() - started_at
        total_bytes = sum(
            Path(file).stat().st_size for file in downloaded_files
            if Path(file).is_file()
        )
        count = len(downloaded_files)
        noun = 'file' if count == 1 else 'files'
        summary = f"{count} {noun} · {format_size(total_bytes)} · {elapsed:.1f}s"
        if skipped:
            summary += f" · {skipped} skipped"
        self.out(style(summary, 'dim'))
        self.out()

        return downloaded_files[0] if len(downloaded_files) == 1 else downloaded_files

    def list_formats(self, url):
        """
        List all available formats for a URL

        Args:
            url: Instagram URL
        """
        info = self.get_info(url)

        print(f"\nMedia: {info.get('title', 'Untitled')}")
        print(f"Uploader: @{info.get('uploader', 'unknown')}")
        print(f"Type: {info.get('type', 'unknown')}")
        print(f"{'='*70}\n")

        entries = info.get('entries') or []
        if any(e['kind'] == 'video' for e in entries):
            print("Dimensions are as reported by Instagram for the original upload;")
            print("the file served to a logged-out client may be a smaller transcode.\n")

        for index, entry in enumerate(entries, 1):
            print(f"Item {index} ({entry['kind']}):")
            for fmt in entry['formats']:
                width = fmt.get('width') or '?'
                height = fmt.get('height') or '?'
                if entry['kind'] == 'video':
                    audio = (f"{self.sym['audio']} WITH AUDIO" if fmt.get('has_audio')
                             else f"{self.sym['muted']} NO AUDIO")
                    print(f"  {fmt.get('format_id')}: {width}x{height} [{audio}]")
                else:
                    print(f"  {fmt.get('format_id')}: {width}x{height}")
            print()

        if info.get('thumbnail'):
            print(f"Thumbnail: {info['thumbnail'][:60]}...")
            print()

        return info
