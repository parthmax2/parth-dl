"""
Core downloader class - orchestrates extraction and downloading
"""

import os
import urllib.error
import urllib.request
from pathlib import Path

from .extractors import MediaExtractor, ProfilePictureExtractor
from .utils import (
    DownloadError,
    NetworkError,
    ProgressBar,
    RateLimiter,
    RateLimitError,
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
    symbols,
    validate_media_url,
    validate_url,
)


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
                 progress_hook=None):
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
        self.rate_limiter = RateLimiter(max_requests=30, time_window=60) if rate_limit else None
        self.sym = symbols()

        # Initialize extractors
        self.media_extractor = MediaExtractor(verbose=verbose)
        self.profile_extractor = ProfilePictureExtractor(verbose=verbose)

    def log(self, message):
        """Print verbose log messages"""
        if self.verbose:
            print(f"[parth-dl] {message}")

    def out(self, message=''):
        """Print user-facing progress output unless quiet"""
        if not self.quiet:
            print(message)

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

        # Rate limiting
        if self.rate_limiter:
            self.rate_limiter.wait_if_needed()

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
            return urllib.request.urlopen(req, timeout=60)

        except urllib.error.HTTPError as e:
            if e.code in (403, 404, 410):
                # The CDN URL has expired or the content is gone; retrying the
                # same URL cannot help - the caller must re-extract.
                raise DownloadError(
                    f"HTTP {e.code}: media URL is no longer valid (expired or removed)"
                )
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
        resume_from = part_path.stat().st_size if part_path.exists() else 0

        if self.rate_limiter:
            self.rate_limiter.wait_if_needed()

        headers = dict(self.BASE_HEADERS)
        if resume_from:
            headers['Range'] = f'bytes={resume_from}-'
            self.log(f"Resuming from {format_size(resume_from)}")

        try:
            response = self._open_url(url, headers)
        except DownloadError:
            # A stale .part can make the server reject the Range; start over once.
            if resume_from:
                self.log("Resume rejected, restarting download")
                part_path.unlink(missing_ok=True)
                resume_from = 0
                response = self._open_url(url, dict(self.BASE_HEADERS))
            else:
                raise

        with response:
            # A server that ignores our Range replies 200 and resends from byte 0.
            resumed = response.getcode() == 206
            if resume_from and not resumed:
                self.log("Server ignored Range request, restarting from zero")
                resume_from = 0

            content_length = int(response.headers.get('Content-Length') or 0)
            total_size = content_length + resume_from if content_length else 0

            progress = None
            if show_progress and not self.quiet and total_size > 0:
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

        # Truncated transfers are the common failure mode; catching it here turns
        # a silently corrupt file into a retry.
        written = part_path.stat().st_size
        if total_size and written != total_size:
            raise NetworkError(
                f"Incomplete download: got {format_size(written)} of {format_size(total_size)}"
            )

        os.replace(part_path, output_path)
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
            # A single -o name cannot hold N carousel children, so index it:
            # photo.jpg -> photo_01.jpg, photo_02.jpg, ...
            return output_path.with_name(
                f"{output_path.stem}_{index:02d}{output_path.suffix}"
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
        """Print the resolution of the downloaded file, preferring the real one"""
        claimed = (fmt.get('width'), fmt.get('height'))

        actual = read_mp4_dimensions(file_path) if entry['kind'] == 'video' else None
        if actual:
            width, height = actual
            if claimed != (None, None) and claimed != actual:
                self.log(f"Instagram reported {claimed[0]}x{claimed[1]} for the source upload")
            self.out(f"Resolution: {width}x{height}")

        elif all(claimed):
            self.out(f"Resolution: {claimed[0]}x{claimed[1]}")

    def download(self, url, output_path=None, quality='best'):
        """
        Download media from Instagram URL

        Args:
            url: Instagram URL (post, reel, or profile)
            output_path: Output file path, or a directory to write into
            quality: 'best' or 'worst'

        Returns:
            Path (or list of paths) to the downloaded file(s)
        """
        info = self.get_info(url)

        if not info or not info.get('entries'):
            raise DownloadError("No downloadable content found")

        # -o may name either a file or a directory. Treat it as a directory when
        # it exists as one, or when it looks like one (trailing separator / no
        # extension) - and create it, rather than failing with ENOENT.
        output_dir = os.getcwd()
        if output_path:
            candidate = Path(output_path)
            looks_like_dir = (
                candidate.is_dir()
                or str(output_path).endswith(('/', '\\'))
                or not candidate.suffix
            )
            if looks_like_dir:
                candidate.mkdir(parents=True, exist_ok=True)
                output_dir, output_path = candidate, None

        entries = info['entries']
        total = len(entries)
        downloaded_files = []
        skipped = 0

        self.out(f"\n{'='*70}")
        self.out(f"Title: {info.get('title', 'Untitled')}")
        self.out(f"Uploader: @{info.get('uploader', 'unknown')}")
        self.out(f"Type: {info.get('type')}")
        if total > 1:
            self.out(f"Items: {total}")
        self.out(f"{'='*70}\n")

        for index, entry in enumerate(entries, 1):
            fmt = self._select_best_format(entry['formats'], quality)
            if not fmt:
                self.out(f"[{index}/{total}] {self.sym['warn']} no usable format, skipping")
                continue

            file_path = self._build_path(info, entry, index, total, output_dir, output_path, fmt)

            if file_path.exists() and not self.overwrite:
                self.out(f"[{index}/{total}] {self.sym['warn']} {file_path.name} already exists "
                         f"(use --force to overwrite)")
                skipped += 1
                continue

            prefix = f"[{index}/{total}] " if total > 1 else ""
            self.out(f"{prefix}{file_path.name}")

            if entry['kind'] == 'video':
                audio = f"{self.sym['ok']} YES" if fmt.get('has_audio') else f"{self.sym['fail']} NO"
                self.out(f"Audio: {audio}")

            self._download_file(fmt['url'], file_path, show_progress=(total == 1))
            downloaded_files.append(str(file_path))

            # Report the resolution of the file we actually got, not the one
            # Instagram advertises for the original upload - they differ, because
            # a logged-out client is served a smaller transcode.
            self._report_resolution(file_path, entry, fmt)
            self.out()

        if not downloaded_files:
            if skipped:
                self.out(f"{self.sym['ok']} Nothing to do - all {skipped} file(s) already present\n")
                return []
            raise DownloadError("No downloadable content found")

        self.out(f"{'='*70}")
        self.out(f"{self.sym['ok']} Download complete!")
        self.out(f"Files saved: {len(downloaded_files)}")
        # Each path is emitted as a file:// link so it can be clicked straight
        # out of the terminal into the system video player.
        for file in downloaded_files:
            self.out(f"  - {hyperlink(file, file_uri(file))}")
        if skipped:
            self.out(f"Skipped (already present): {skipped}")
        self.out(f"Source: {hyperlink(url, url)}")
        self.out(f"{'='*70}\n")

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
