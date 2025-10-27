"""
parth-dl: Instagram Media Downloader
Download Instagram reels, posts, and profile pictures (public accounts only)

Author: Parth
License: MIT
"""

__version__ = "1.0.0"
__author__ = "Parth"
__description__ = "Instagram media downloader for public content"

from .core import InstagramDownloader
from .utils import DownloadError, RateLimitError, NetworkError

__all__ = [
    'InstagramDownloader',
    'DownloadError',
    'RateLimitError', 
    'NetworkError',
]


def download(url, output_path=None, quality='best', verbose=False):
    """
    Quick download function
    
    Args:
        url: Instagram URL (reel, post, or profile)
        output_path: Output file/directory path
        quality: 'best' or 'worst'
        verbose: Enable verbose logging
        
    Returns:
        Path to downloaded file(s)
    """
    downloader = InstagramDownloader(verbose=verbose)
    return downloader.download(url, output_path, quality)


def get_info(url, verbose=False):
    """
    Get media information without downloading
    
    Args:
        url: Instagram URL
        verbose: Enable verbose logging
        
    Returns:
        Dictionary with media information
    """
    downloader = InstagramDownloader(verbose=verbose)
    return downloader.get_info(url)