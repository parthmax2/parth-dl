"""
Instagram-specific extractors for different content types
Each extractor handles parsing and validation
"""

import re
import json
import urllib.request
import urllib.parse
from .utils import (
    retry_on_failure, RateLimitError, NetworkError, 
    DownloadError, extract_instagram_id, extract_username
)


class BaseExtractor:
    """Base class for all extractors"""
    
    BASE_HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': '*/*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'Origin': 'https://www.instagram.com',
        'Referer': 'https://www.instagram.com/',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-site',
    }
    
    API_HEADERS = {
        'X-IG-App-ID': '936619743392459',
        'X-ASBD-ID': '198387',
        'X-IG-WWW-Claim': '0',
    }
    
    def __init__(self, verbose=False):
        self.verbose = verbose
        self.cookies = {}
    
    def log(self, message):
        """Print verbose log messages"""
        if self.verbose:
            print(f"[Extractor] {message}")
    
    @retry_on_failure(max_retries=3)
    def _make_request(self, url, headers=None, data=None, decode=True):
        """Make HTTP request with retry logic and error handling"""
        request_headers = {**self.BASE_HEADERS}
        if headers:
            request_headers.update(headers)
        
        try:
            if data:
                data = urllib.parse.urlencode(data).encode()
            
            req = urllib.request.Request(url, data=data, headers=request_headers)
            response = urllib.request.urlopen(req, timeout=30)
            
            # Store cookies
            if hasattr(response, 'headers'):
                for cookie in response.headers.get_all('Set-Cookie', []):
                    parts = cookie.split(';')[0].split('=', 1)
                    if len(parts) == 2:
                        self.cookies[parts[0]] = parts[1]
            
            content = response.read()
            
            # Handle gzip compression
            if response.headers.get('Content-Encoding') == 'gzip':
                import gzip
                content = gzip.decompress(content)
            
            # Handle brotli compression (Instagram sometimes uses this)
            elif response.headers.get('Content-Encoding') == 'br':
                try:
                    import brotli
                    content = brotli.decompress(content)
                except ImportError:
                    # If brotli not available, try without decompression
                    pass
            
            # Return decoded text or raw bytes
            if decode:
                # Try multiple encodings
                for encoding in ['utf-8', 'latin-1', 'iso-8859-1']:
                    try:
                        return content.decode(encoding)
                    except UnicodeDecodeError:
                        continue
                # If all fail, return with error replacement
                return content.decode('utf-8', errors='replace')
            else:
                return content
        
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise DownloadError("Content not found. It might be private or deleted.")
            elif e.code == 429:
                raise RateLimitError("Rate limited by Instagram. Please wait before retrying.")
            elif e.code == 403:
                raise DownloadError("Access forbidden. Content might be private.")
            else:
                raise NetworkError(f"HTTP {e.code}: {e.reason}")
        
        except urllib.error.URLError as e:
            raise NetworkError(f"Network error: {e.reason}")
        
        except Exception as e:
            raise NetworkError(f"Request failed: {str(e)}")
    
    def _shortcode_to_mediaid(self, shortcode):
        """Convert Instagram shortcode to media ID"""
        alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_'
        media_id = 0
        
        for char in shortcode:
            media_id = media_id * 64 + alphabet.index(char)
        
        return str(media_id)
    
    def _mediaid_to_shortcode(self, media_id):
        """Convert media ID back to shortcode"""
        alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_'
        media_id = int(str(media_id).split('_')[0])
        shortcode = ''
        
        while media_id > 0:
            remainder = media_id % 64
            media_id //= 64
            shortcode = alphabet[remainder] + shortcode
        
        return shortcode


class MediaExtractor(BaseExtractor):
    """Extract posts and reels (videos/images)"""
    
    API_BASE = 'https://i.instagram.com/api/v1'
    
    def extract(self, url):
        """
        Extract media information from Instagram URL
        Returns dict with formats, thumbnail, metadata
        """
        shortcode = extract_instagram_id(url)
        if not shortcode:
            raise DownloadError("Invalid Instagram media URL")
        
        self.log(f"Extracting media: {shortcode}")
        
        # Try multiple methods in order
        methods = [
            ('API', lambda: self._extract_from_api(shortcode)),
            ('Direct Page', lambda: self._extract_from_page(shortcode)),
            ('GraphQL', lambda: self._extract_from_graphql(shortcode)),
            ('Embed', lambda: self._extract_from_embed(shortcode)),
        ]
        
        for method_name, method in methods:
            try:
                self.log(f"Attempting {method_name} extraction...")
                result = method()
                if result and (result.get('formats') or result.get('images')):
                    self.log(f"✓ {method_name} extraction successful!")
                    return result
                else:
                    self.log(f"✗ {method_name} returned no data")
            except Exception as e:
                self.log(f"✗ {method_name} failed: {e}")
                continue
        
        raise DownloadError("All extraction methods failed. Content might be private or unavailable.")
    
    def _extract_from_api(self, shortcode):
        """Extract using Instagram API (primary method)"""
        self.log("Trying API extraction...")
        
        media_id = self._shortcode_to_mediaid(shortcode)
        self.log(f"Converted shortcode '{shortcode}' to media_id: {media_id}")
        
        # Setup session - visit post page first
        post_url = f'https://www.instagram.com/p/{shortcode}/'
        try:
            self._make_request(post_url)
            self.log("Session setup successful")
        except Exception as e:
            self.log(f"Session setup warning: {e}")
        
        # API request
        api_url = f'{self.API_BASE}/media/{media_id}/info/'
        headers = {**self.API_HEADERS}
        
        if 'csrftoken' in self.cookies:
            headers['X-CSRFToken'] = self.cookies['csrftoken']
        
        try:
            response = self._make_request(api_url, headers=headers)
            data = json.loads(response)
            
            self.log(f"API response status: {data.get('status', 'unknown')}")
            
            if 'items' in data and len(data['items']) > 0:
                self.log(f"Found {len(data['items'])} item(s) in API response")
                return self._parse_media_item(data['items'][0])
            else:
                self.log("No items in API response")
        except Exception as e:
            self.log(f"API extraction error: {e}")
        
        return None
    
    def _extract_from_graphql(self, shortcode):
        """Extract using GraphQL (fallback)"""
        self.log("Trying GraphQL extraction...")
        
        variables = {
            'shortcode': shortcode,
            'child_comment_count': 0,
            'fetch_comment_count': 0,
            'parent_comment_count': 0,
            'has_threaded_comments': False,
        }
        
        headers = {
            **self.API_HEADERS,
            'X-CSRFToken': self.cookies.get('csrftoken', ''),
            'X-Requested-With': 'XMLHttpRequest',
        }
        
        query_url = f"https://www.instagram.com/graphql/query/?doc_id=8845758582119845&variables={urllib.parse.quote(json.dumps(variables))}"
        
        try:
            response = self._make_request(query_url, headers=headers)
            data = json.loads(response)
            
            self.log(f"GraphQL response keys: {list(data.keys())}")
            
            media = data.get('data', {}).get('xdt_shortcode_media', {})
            if media:
                self.log("Found media in GraphQL response")
                return self._parse_graphql_media(media)
            else:
                self.log("No media found in GraphQL response")
        except Exception as e:
            self.log(f"GraphQL extraction error: {e}")
        
        return None
    
    def _extract_from_embed(self, shortcode):
        """Extract from embed page (last resort)"""
        self.log("Trying embed extraction...")
        
        embed_url = f'https://www.instagram.com/p/{shortcode}/embed/'
        
        try:
            webpage = self._make_request(embed_url)
            self.log(f"Embed page loaded, length: {len(webpage)} chars")
            
            # Look for __additionalDataLoaded
            match = re.search(r'window\.__additionalDataLoaded\s*\(\s*[^,]+,\s*({.+?})\s*\)', webpage, re.DOTALL)
            if match:
                self.log("Found __additionalDataLoaded data")
                data = json.loads(match.group(1))
                
                # Try items format
                item = data.get('items', [{}])[0]
                if item:
                    self.log("Found item in items format")
                    return self._parse_media_item(item)
                
                # Try graphql format
                media = data.get('graphql', {}).get('shortcode_media') or data.get('shortcode_media')
                if media:
                    self.log("Found media in graphql format")
                    return self._parse_graphql_media(media)
            else:
                self.log("__additionalDataLoaded not found")
                
                # Try alternative: window._sharedData
                match = re.search(r'window\._sharedData\s*=\s*({.+?});\s*</script>', webpage, re.DOTALL)
                if match:
                    self.log("Found _sharedData")
                    data = json.loads(match.group(1))
                    entry_data = data.get('entry_data', {})
                    
                    # Try PostPage
                    post_page = entry_data.get('PostPage', [{}])[0]
                    media = post_page.get('graphql', {}).get('shortcode_media')
                    if media:
                        self.log("Found media in PostPage")
                        return self._parse_graphql_media(media)
        except Exception as e:
            self.log(f"Embed extraction error: {e}")
        
        return None
    
    def _parse_media_item(self, item):
        """Parse API format media item"""
        result = {
            'id': self._mediaid_to_shortcode(item.get('pk', '')),
            'title': '',
            'formats': [],
            'images': [],
            'thumbnail': None,
            'duration': item.get('video_duration'),
            'uploader': item.get('user', {}).get('username', 'unknown'),
            'type': 'video' if item.get('video_versions') else 'image',
        }
        
        # Set title
        caption = item.get('caption', {})
        if isinstance(caption, dict):
            result['title'] = caption.get('text', '')[:100]
        result['title'] = result['title'] or f"Media by {result['uploader']}"
        
        # Video formats (with audio)
        video_versions = item.get('video_versions', [])
        for idx, video in enumerate(video_versions):
            result['formats'].append({
                'url': video.get('url'),
                'width': video.get('width'),
                'height': video.get('height'),
                'format_id': f"video-{idx}",
                'has_audio': True,
                'type': 'video',
            })
        
        # Image formats (for posts)
        image_versions = item.get('image_versions2', {}).get('candidates', [])
        if image_versions and not video_versions:
            for idx, image in enumerate(image_versions):
                result['images'].append({
                    'url': image.get('url'),
                    'width': image.get('width'),
                    'height': image.get('height'),
                    'format_id': f"image-{idx}",
                })
        
        # Carousel (multiple images/videos)
        carousel_media = item.get('carousel_media', [])
        if carousel_media:
            result['type'] = 'carousel'
            for idx, media_item in enumerate(carousel_media):
                if media_item.get('video_versions'):
                    for video in media_item['video_versions']:
                        result['formats'].append({
                            'url': video.get('url'),
                            'width': video.get('width'),
                            'height': video.get('height'),
                            'format_id': f"carousel-video-{idx}",
                            'has_audio': True,
                            'type': 'video',
                        })
                else:
                    candidates = media_item.get('image_versions2', {}).get('candidates', [])
                    if candidates:
                        result['images'].append({
                            'url': candidates[0].get('url'),
                            'width': candidates[0].get('width'),
                            'height': candidates[0].get('height'),
                            'format_id': f"carousel-image-{idx}",
                        })
        
        # Thumbnail
        thumbnails = image_versions
        if thumbnails:
            result['thumbnail'] = thumbnails[0].get('url')
        
        return result
    
    def _parse_graphql_media(self, media):
        """Parse GraphQL format media"""
        result = {
            'id': media.get('shortcode', ''),
            'title': '',
            'formats': [],
            'images': [],
            'thumbnail': None,
            'duration': media.get('video_duration'),
            'uploader': media.get('owner', {}).get('username', 'unknown'),
            'type': 'video' if media.get('is_video') else 'image',
        }
        
        # Caption
        edges = media.get('edge_media_to_caption', {}).get('edges', [])
        if edges:
            result['title'] = edges[0].get('node', {}).get('text', '')[:100]
        result['title'] = result['title'] or f"Media by {result['uploader']}"
        
        # Video
        video_url = media.get('video_url')
        if video_url:
            dims = media.get('dimensions', {})
            result['formats'].append({
                'url': video_url,
                'width': dims.get('width'),
                'height': dims.get('height'),
                'format_id': 'graphql-video',
                'has_audio': True,
                'type': 'video',
            })
        
        # Image
        display_url = media.get('display_url')
        if display_url and not video_url:
            dims = media.get('dimensions', {})
            result['images'].append({
                'url': display_url,
                'width': dims.get('width'),
                'height': dims.get('height'),
                'format_id': 'graphql-image',
            })
        
        # Thumbnail
        result['thumbnail'] = media.get('display_url') or media.get('thumbnail_src')
        
        return result


class ProfilePictureExtractor(BaseExtractor):
    """Extract profile pictures"""
    
    def extract(self, url):
        """Extract profile picture URL"""
        username = extract_username(url)
        if not username:
            raise DownloadError("Invalid Instagram profile URL")
        
        self.log(f"Extracting profile picture for: {username}")
        
        # Try multiple methods
        methods = [
            self._extract_from_web,
            self._extract_from_api,
        ]
        
        for method in methods:
            try:
                result = method(username)
                if result:
                    return result
            except Exception as e:
                self.log(f"Method failed: {e}")
                continue
        
        raise DownloadError(f"Could not extract profile picture for @{username}")
    
    def _extract_from_web(self, username):
        """Extract from profile web page"""
        self.log("Trying web extraction...")
        
        profile_url = f'https://www.instagram.com/{username}/'
        
        # Get page content with proper encoding handling
        webpage = self._make_request(profile_url, decode=True)
        
        # Extract profile data from page
        patterns = [
            r'"profile_pic_url_hd":"([^"]+)"',
            r'"profile_pic_url":"([^"]+)"',
            r'profilePage_([0-9]+)\\?"profile_pic_url\\?":\\?"([^"]+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, webpage)
            if match:
                # Get URL from correct group
                pic_url = match.group(1) if '(' in pattern and match.lastindex == 1 else match.group(match.lastindex)
                pic_url = pic_url.replace('\\u0026', '&').replace('\\/', '/')
                
                return {
                    'id': username,
                    'title': f"{username}'s profile picture",
                    'uploader': username,
                    'type': 'profile_picture',
                    'formats': [],
                    'images': [{
                        'url': pic_url,
                        'format_id': 'profile-pic-hd',
                        'type': 'image',
                    }],
                    'thumbnail': pic_url,
                }
        
        return None
    
    def _extract_from_api(self, username):
        """Extract using Instagram API"""
        self.log("Trying API extraction...")
        
        # Try public API endpoint
        api_url = f'https://www.instagram.com/api/v1/users/web_profile_info/?username={username}'
        
        headers = {
            **self.API_HEADERS,
            'X-CSRFToken': self.cookies.get('csrftoken', ''),
            'X-Requested-With': 'XMLHttpRequest',
        }
        
        try:
            response = self._make_request(api_url, headers=headers, decode=True)
            data = json.loads(response)
            
            user = data.get('data', {}).get('user', {})
            if user:
                pic_url = user.get('profile_pic_url_hd') or user.get('profile_pic_url')
                
                if pic_url:
                    return {
                        'id': username,
                        'title': f"{username}'s profile picture",
                        'uploader': username,
                        'type': 'profile_picture',
                        'formats': [],
                        'images': [{
                            'url': pic_url,
                            'format_id': 'profile-pic-hd',
                            'type': 'image',
                        }],
                        'thumbnail': pic_url,
                    }
        except Exception as e:
            self.log(f"API extraction error: {e}")
        
        return None