"""
Utility functions: retry logic, rate limiting, error handling
Security-focused with yt-dlp-inspired reliability
"""

import time
import re
from functools import wraps
from typing import Callable, Any


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


class RateLimiter:
    """Token bucket rate limiter to prevent IP bans"""
    
    def __init__(self, max_requests=30, time_window=60):
        """
        Args:
            max_requests: Maximum requests allowed
            time_window: Time window in seconds
        """
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = []
    
    def wait_if_needed(self):
        """Block if rate limit would be exceeded"""
        now = time.time()
        
        # Remove old requests outside window
        self.requests = [req_time for req_time in self.requests 
                        if now - req_time < self.time_window]
        
        if len(self.requests) >= self.max_requests:
            # Calculate wait time
            oldest_request = min(self.requests)
            wait_time = self.time_window - (now - oldest_request)
            
            if wait_time > 0:
                time.sleep(wait_time + 0.1)  # Small buffer
                self.requests = []
        
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
                
                except RateLimitError:
                    # Don't retry rate limits, fail fast
                    raise
                
                except (NetworkError, ConnectionError, TimeoutError) as e:
                    last_exception = e
                    
                    if attempt < max_retries - 1:
                        delay = backoff.get_delay(attempt)
                        time.sleep(delay)
                    else:
                        raise NetworkError(f"Failed after {max_retries} attempts: {e}")
                
                except Exception as e:
                    # Unknown errors don't retry
                    raise DownloadError(f"Unexpected error: {e}")
            
            raise NetworkError(f"Failed after {max_retries} attempts: {last_exception}")
        
        return wrapper
    return decorator


def sanitize_filename(filename, max_length=200):
    """
    Sanitize filename for safe filesystem operations
    Security: Prevent directory traversal and invalid characters
    """
    if not filename:
        return "untitled"
    
    # Remove path separators and dangerous characters
    filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', filename)
    
    # Remove leading/trailing spaces and dots
    filename = filename.strip('. ')
    
    # Replace multiple spaces/dashes with single
    filename = re.sub(r'[\s-]+', '_', filename)
    
    # Limit length
    if len(filename) > max_length:
        filename = filename[:max_length]
    
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
    
    # Check for suspicious patterns
    dangerous_patterns = [
        r'javascript:',
        r'data:',
        r'file:',
        r'<script',
        r'\.\./',  # Directory traversal
    ]
    
    for pattern in dangerous_patterns:
        if re.search(pattern, url, re.IGNORECASE):
            raise ValidationError("URL contains potentially dangerous content")
    
    return True


def format_size(size_bytes):
    """Format bytes into human-readable size"""
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
    # Remove query parameters and fragments
    url = url.split('?')[0].split('#')[0]
    
    patterns = [
        # Standard formats: /p/, /tv/, /reel/, /reels/
        r'instagram\.com/(?:p|tv|reel|reels)/([A-Za-z0-9_-]+)',
        # Username with post: /username/p/CODE/
        r'instagram\.com/[^/]+/(?:p|reel|reels)/([A-Za-z0-9_-]+)',
        # Stories (for future support)
        r'instagram\.com/stories/[^/]+/([A-Za-z0-9_-]+)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    
    return None


def extract_username(url):
    """Extract Instagram username from URL"""
    # Remove query parameters
    url = url.split('?')[0]
    
    # Match /@username or /username (but not /p/, /reel/, etc.)
    patterns = [
        r'instagram\.com/@([A-Za-z0-9_.]+)/?$',
        r'instagram\.com/([A-Za-z0-9_.]+)/?$',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            username = match.group(1)
            # Exclude reserved paths
            if username not in ['p', 'reel', 'reels', 'tv', 'stories', 'explore', 'accounts']:
                return username
    
    return None


def is_profile_url(url):
    """Check if URL is a profile URL (for DP download)"""
    return extract_username(url) is not None


def is_media_url(url):
    """Check if URL is a media URL (post/reel)"""
    return extract_instagram_id(url) is not None


class ProgressBar:
    """Simple progress bar for downloads"""
    
    def __init__(self, total_size, desc="Downloading"):
        self.total_size = total_size
        self.desc = desc
        self.downloaded = 0
        self.start_time = time.time()
    
    def update(self, chunk_size):
        """Update progress"""
        self.downloaded += chunk_size
        
        if self.total_size > 0:
            percent = (self.downloaded / self.total_size) * 100
            speed = self.downloaded / (time.time() - self.start_time + 0.001)
            
            bar_length = 40
            filled = int(bar_length * self.downloaded / self.total_size)
            bar = '█' * filled + '░' * (bar_length - filled)
            
            print(f'\r{self.desc}: |{bar}| {percent:.1f}% '
                  f'{format_size(self.downloaded)}/{format_size(self.total_size)} '
                  f'@ {format_size(speed)}/s', end='', flush=True)
    
    def finish(self):
        """Complete the progress bar"""
        print()  # New line