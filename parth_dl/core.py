"""
Core downloader class - orchestrates extraction and downloading
"""

import os
import urllib.request
from pathlib import Path
from .extractors import MediaExtractor, ProfilePictureExtractor
from .utils import (
    validate_url, sanitize_filename, is_profile_url, is_media_url,
    RateLimiter, ProgressBar, DownloadError, format_size, retry_on_failure
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
    
    def __init__(self, verbose=False, rate_limit=True):
        """
        Initialize downloader
        
        Args:
            verbose: Enable verbose logging
            rate_limit: Enable rate limiting (recommended)
        """
        self.verbose = verbose
        self.rate_limiter = RateLimiter(max_requests=30, time_window=60) if rate_limit else None
        
        # Initialize extractors
        self.media_extractor = MediaExtractor(verbose=verbose)
        self.profile_extractor = ProfilePictureExtractor(verbose=verbose)
    
    def log(self, message):
        """Print verbose log messages"""
        if self.verbose:
            print(f"[parth-dl] {message}")
    
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
        
        # Determine content type and extract
        if is_profile_url(url):
            self.log("Detected profile URL")
            return self.profile_extractor.extract(url)
        elif is_media_url(url):
            self.log("Detected media URL")
            return self.media_extractor.extract(url)
        else:
            raise DownloadError("Unsupported URL format. Use post/reel/profile URL.")
    
    @retry_on_failure(max_retries=3)
    def _download_file(self, url, output_path, show_progress=True):
        """
        Download file with progress bar
        
        Args:
            url: Direct download URL
            output_path: Output file path
            show_progress: Show download progress
        """
        req = urllib.request.Request(url, headers=self.BASE_HEADERS)
        
        with urllib.request.urlopen(req, timeout=60) as response:
            total_size = int(response.headers.get('Content-Length', 0))
            
            # Create progress bar
            progress = None
            if show_progress and total_size > 0:
                progress = ProgressBar(total_size)
            
            # Download
            with open(output_path, 'wb') as f:
                while True:
                    chunk = response.read(8192)
                    if not chunk:
                        break
                    
                    f.write(chunk)
                    if progress:
                        progress.update(len(chunk))
            
            if progress:
                progress.finish()
        
        self.log(f"Downloaded: {output_path} ({format_size(os.path.getsize(output_path))})")
    
    def _select_best_format(self, formats, quality='best'):
        """
        Select best format based on quality preference
        
        Args:
            formats: List of format dictionaries
            quality: 'best' or 'worst'
            
        Returns:
            Selected format dictionary
        """
        if not formats:
            return None
        
        # Filter to only formats with audio (for videos)
        video_formats = [f for f in formats if f.get('has_audio')]
        if video_formats:
            formats = video_formats
        
        if quality == 'best':
            # Best: highest resolution
            return max(formats, key=lambda f: (
                f.get('height', 0) * f.get('width', 0),
                f.get('height', 0)
            ))
        else:
            # Worst: lowest resolution
            return min(formats, key=lambda f: (
                f.get('height', 999999),
                f.get('width', 999999)
            ))
    
    def download(self, url, output_path=None, quality='best'):
        """
        Download media from Instagram URL
        
        Args:
            url: Instagram URL (post, reel, or profile)
            output_path: Output file/directory path (auto-generated if None)
            quality: 'best' or 'worst'
            
        Returns:
            Path(s) to downloaded file(s)
        """
        # Get media info
        info = self.get_info(url)
        
        if not info:
            raise DownloadError("Failed to extract media information")
        
        # Prepare output directory
        if output_path and os.path.isdir(output_path):
            output_dir = output_path
            output_path = None
        else:
            output_dir = os.getcwd()
        
        # Handle different media types
        media_type = info.get('type')
        downloaded_files = []
        
        print(f"\n{'='*70}")
        print(f"Title: {info.get('title', 'Untitled')}")
        print(f"Uploader: @{info.get('uploader', 'unknown')}")
        print(f"Type: {media_type}")
        print(f"{'='*70}\n")
        
        # Download videos
        if info.get('formats'):
            selected_format = self._select_best_format(info['formats'], quality)
            
            if not selected_format:
                raise DownloadError("No suitable video format found")
            
            # Generate filename
            if not output_path:
                safe_title = sanitize_filename(info.get('title', 'video'))
                media_id = info.get('id', 'unknown')
                output_path = os.path.join(output_dir, f"{safe_title}_{media_id}.mp4")
            
            print(f"Resolution: {selected_format.get('width')}x{selected_format.get('height')}")
            print(f"Audio: {'✓ YES' if selected_format.get('has_audio') else '✗ NO'}")
            print(f"Output: {output_path}\n")
            
            self._download_file(selected_format['url'], output_path)
            downloaded_files.append(output_path)
        
        # Download images
        elif info.get('images'):
            images = info['images']
            
            if len(images) == 1:
                # Single image
                if not output_path:
                    safe_title = sanitize_filename(info.get('title', 'image'))
                    media_id = info.get('id', 'unknown')
                    output_path = os.path.join(output_dir, f"{safe_title}_{media_id}.jpg")
                
                print(f"Output: {output_path}\n")
                self._download_file(images[0]['url'], output_path)
                downloaded_files.append(output_path)
            
            else:
                # Multiple images (carousel)
                print(f"Downloading {len(images)} images from carousel...\n")
                
                safe_title = sanitize_filename(info.get('title', 'carousel'))
                media_id = info.get('id', 'unknown')
                
                for idx, image in enumerate(images, 1):
                    filename = f"{safe_title}_{media_id}_{idx:02d}.jpg"
                    file_path = os.path.join(output_dir, filename)
                    
                    print(f"[{idx}/{len(images)}] {filename}")
                    self._download_file(image['url'], file_path, show_progress=False)
                    downloaded_files.append(file_path)
                    print()
        
        else:
            raise DownloadError("No downloadable content found")
        
        # Success message
        print(f"{'='*70}")
        print(f"✓ Download complete!")
        print(f"Files saved: {len(downloaded_files)}")
        for file in downloaded_files:
            print(f"  - {file}")
        print(f"{'='*70}\n")
        
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
        
        # Video formats
        if info.get('formats'):
            print("Video Formats:")
            for fmt in info['formats']:
                audio = "🔊 WITH AUDIO" if fmt.get('has_audio') else "🔇 NO AUDIO"
                print(f"  {fmt.get('format_id')}: {fmt.get('width')}x{fmt.get('height')} [{audio}]")
            print()
        
        # Image formats
        if info.get('images'):
            print(f"Images: {len(info['images'])} image(s)")
            for idx, img in enumerate(info['images'], 1):
                print(f"  [{idx}] {img.get('width')}x{img.get('height')}")
            print()
        
        # Thumbnail
        if info.get('thumbnail'):
            print(f"Thumbnail: {info['thumbnail'][:60]}...")
            print()