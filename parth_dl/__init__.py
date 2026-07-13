"""
parth-dl: Instagram Media Downloader
Download Instagram reels, posts, and profile pictures (public accounts only)

Author: Saksham Pathak (Parthmax)
License: MIT
"""

__version__ = "1.1.0"
__author__ = "Saksham Pathak (Parthmax)"
__description__ = "Instagram media downloader for public content"

from .core import InstagramDownloader
from .utils import DownloadError, NetworkError, RateLimitError, ValidationError

__all__ = [
    'InstagramDownloader',
    'download',
    'get_info',
    'DownloadError',
    'RateLimitError',
    'NetworkError',
    'ValidationError',
]


def download(url, output_path=None, quality='best', verbose=False):
    """
    Download media from an Instagram URL.

    Args:
        url: Instagram URL (reel, post, or profile)
        output_path: Output file path, or a directory to write into
        quality: 'best' or 'worst'
        verbose: Enable verbose logging

    Returns:
        A path (single item) or list of paths (carousel) to the downloaded file(s)

    Raises:
        ValidationError: the URL is not a supported Instagram URL
        RateLimitError: Instagram is rate limiting this IP
        NetworkError: the transfer failed after retries
        DownloadError: the content is private, deleted, or unsupported
    """
    downloader = InstagramDownloader(verbose=verbose)
    return downloader.download(url, output_path, quality)


def get_info(url, verbose=False):
    """
    Fetch media metadata without downloading anything.

    Args:
        url: Instagram URL (reel, post, or profile)
        verbose: Enable verbose logging

    Returns:
        A metadata dict - see docs/schema.md for the full field reference.

    Raises:
        Same as download().
    """
    downloader = InstagramDownloader(verbose=verbose)
    return downloader.get_info(url)
