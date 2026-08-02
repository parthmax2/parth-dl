"""
Instagram-specific extractors for different content types
Each extractor handles parsing and validation
"""

import http.cookiejar
import json
import re
import sys
import urllib.parse
import urllib.request

from .utils import (
    DownloadError,
    NetworkError,
    RateLimitError,
    extract_instagram_id,
    extract_username,
    finalize_info,
    format_caption,
    retry_on_failure,
)


class BaseExtractor:
    """Base class for all extractors"""

    BASE_HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': '*/*',
        'Accept-Language': 'en-US,en;q=0.9',
        # urllib does not decode Content-Encoding automatically. Advertise only
        # gzip, which the standard library can decode below.
        'Accept-Encoding': 'gzip',
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

    def __init__(self, verbose=False, rate_limiter=None):
        self.verbose = verbose
        self.rate_limiter = rate_limiter
        # A real cookie jar, so Set-Cookie values are actually replayed on later
        # requests. The old code parsed cookies into a dict and never sent them,
        # which is why every endpoint needing a csrftoken answered 403.
        self.cookie_jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookie_jar)
        )

    @property
    def cookies(self):
        """Session cookies as a plain dict (csrftoken, etc.)"""
        return {cookie.name: cookie.value for cookie in self.cookie_jar}

    def log(self, message):
        """Print verbose log messages"""
        if self.verbose:
            print(f"[Extractor] {message}", file=sys.stderr)

    @retry_on_failure(max_retries=3)
    def _make_request(self, url, headers=None, data=None, decode=True):
        """Make HTTP request with retry logic and error handling"""
        request_headers = {**self.BASE_HEADERS}
        if headers:
            request_headers.update(headers)

        try:
            if self.rate_limiter:
                self.rate_limiter.wait_if_needed()

            if data:
                data = urllib.parse.urlencode(data).encode()

            req = urllib.request.Request(url, data=data, headers=request_headers)
            response = self.opener.open(req, timeout=30)

            content = response.read()

            # Handle gzip compression
            if response.headers.get('Content-Encoding') == 'gzip':
                import gzip
                content = gzip.decompress(content)

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

    ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_'

    def _shortcode_to_mediaid(self, shortcode):
        """Convert Instagram shortcode to media ID"""
        media_id = 0

        for char in shortcode:
            try:
                media_id = media_id * 64 + self.ALPHABET.index(char)
            except ValueError:
                raise DownloadError(f"Malformed shortcode: {shortcode!r}")

        return str(media_id)

    def _mediaid_to_shortcode(self, media_id):
        """Convert media ID back to shortcode"""
        try:
            media_id = int(str(media_id).split('_')[0])
        except (TypeError, ValueError):
            return ''

        shortcode = ''
        while media_id > 0:
            remainder = media_id % 64
            media_id //= 64
            shortcode = self.ALPHABET[remainder] + shortcode

        return shortcode


class MediaExtractor(BaseExtractor):
    """Extract posts and reels (videos/images)"""

    API_BASE = 'https://i.instagram.com/api/v1'
    LOGGED_OUT_QUERY_NAME = 'PolarisLoggedOutDesktopWWWPostRootContentQuery'
    LOGGED_OUT_QUERY_DOC_ID = '27130156389949648'

    def __init__(self, verbose=False, rate_limiter=None, caption_max_length=100):
        super().__init__(verbose=verbose, rate_limiter=rate_limiter)
        self.caption_max_length = caption_max_length

    def _caption_fields(self, caption_text, uploader):
        """Build title/caption metadata from raw Instagram caption text."""
        caption = caption_text or ''
        title = format_caption(caption, self.caption_max_length)
        return {
            'caption': caption,
            'title': title or f"Media by {uploader}",
        }

    def extract(self, url):
        """
        Extract media information from Instagram URL
        Returns dict with formats, thumbnail, metadata
        """
        shortcode = extract_instagram_id(url)
        if not shortcode:
            raise DownloadError("Invalid Instagram media URL")

        self.log(f"Extracting media: {shortcode}")

        # Embed remains the cheapest path for posts Instagram exposes directly.
        # GraphQL then uses the logged-out Polaris endpoint, which covers reels
        # whose embed contains metadata/cover art but deliberately omits the
        # playable URL. The legacy private API is retained as a final fallback.
        methods = [
            ('Embed', self._extract_from_embed),
            ('GraphQL', self._extract_from_graphql),
            ('API', self._extract_from_api),
        ]

        errors = []
        for method_name, method in methods:
            try:
                self.log(f"Attempting {method_name} extraction...")
                result = method(shortcode)
                if result and result.get('entries'):
                    self.log(f"{method_name} extraction successful!")
                    return result
                else:
                    self.log(f"{method_name} returned no data")
            except (RateLimitError, NetworkError, DownloadError) as e:
                # Instagram often 403s one endpoint while another still answers,
                # so every method gets its turn before we give up.
                self.log(f"{method_name} failed: {e}")
                errors.append(e)
            except Exception as e:
                # A parser bug in one fallback must not prevent a later method
                # from succeeding, but it is not mislabeled as a network error.
                self.log(f"{method_name} failed unexpectedly: {e}")
                errors.append(DownloadError(str(e)))

        # Preserve actionable failure types. A 429 takes precedence because
        # trying yet another endpoint makes it worse; otherwise report a network
        # outage before falling back to the generic private/deleted diagnosis.
        for error_type in (RateLimitError, NetworkError):
            matching = [error for error in errors if isinstance(error, error_type)]
            if matching:
                raise matching[-1]

        raise DownloadError(
            "All extraction methods failed. The content may be private or deleted, "
            "or Instagram is serving a login wall to unauthenticated requests."
        )

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
        except (RateLimitError, NetworkError):
            raise
        except DownloadError as e:
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
        except (RateLimitError, NetworkError, DownloadError):
            raise
        except (ValueError, TypeError, KeyError) as e:
            self.log(f"API extraction error: {e}")

        return None

    @staticmethod
    def _extract_lsd_token(webpage):
        """Extract the per-session token required by logged-out GraphQL."""
        patterns = (
            r'\["LSD",\[\],\{"token":"([^"]+)"',
            r'"LSD",\[\],\{"token":"([^"]+)"',
        )
        for pattern in patterns:
            match = re.search(pattern, webpage)
            if match:
                return match.group(1)

        # Some deployments put the token in the JSON body of the __eqmc script.
        match = re.search(
            r'<script\b[^>]*\bid=["\']__eqmc["\'][^>]*>(.*?)</script>',
            webpage, re.DOTALL,
        )
        if match:
            try:
                data = json.loads(match.group(1))
                token = data.get('l')
                if isinstance(token, str):
                    return token
            except (TypeError, ValueError):
                pass
        return None

    def _extract_from_polaris(self, shortcode):
        """Use Instagram's current logged-out web GraphQL flow."""
        self.log("Trying logged-out Polaris GraphQL extraction...")

        homepage = self._make_request('https://www.instagram.com/')
        lsd_token = self._extract_lsd_token(homepage)
        if not lsd_token:
            self.log("Polaris session did not provide an LSD token")
            return None

        media_id = self._shortcode_to_mediaid(shortcode)
        ruling_url = (
            f'{self.API_BASE}/web/get_ruling_for_content/?'
            + urllib.parse.urlencode({
                'content_type': 'MEDIA',
                'target_id': media_id,
            })
        )
        ruling = json.loads(self._make_request(
            ruling_url, headers=self.API_HEADERS,
        ))
        if ruling.get('status') != 'ok':
            detail = ruling.get('title') or ruling.get('description')
            self.log(f"Instagram did not grant anonymous access{': ' + detail if detail else ''}")
            return None

        csrf_token = self.cookies.get('csrftoken', '')
        if not csrf_token:
            self.log("Polaris session did not provide a CSRF token")
            return None

        headers = {
            **self.API_HEADERS,
            'X-FB-Friendly-Name': self.LOGGED_OUT_QUERY_NAME,
            'X-CSRFToken': csrf_token,
            'X-FB-LSD': lsd_token,
            'X-Requested-With': 'XMLHttpRequest',
            'Referer': f'https://www.instagram.com/reel/{shortcode}/',
        }
        payload = {
            'lsd': lsd_token,
            'fb_api_caller_class': 'RelayModern',
            'fb_api_req_friendly_name': self.LOGGED_OUT_QUERY_NAME,
            'server_timestamps': 'true',
            'variables': json.dumps({'media_id': media_id}, separators=(',', ':')),
            'doc_id': self.LOGGED_OUT_QUERY_DOC_ID,
        }
        response = json.loads(self._make_request(
            'https://www.instagram.com/api/graphql',
            headers=headers,
            data=payload,
        ))

        if response.get('errors'):
            self.log(f"Polaris GraphQL returned errors: {response['errors']}")

        media = (response.get('data') or {}).get('xig_polaris_media') or {}
        product = media.get('if_not_gated_logged_out') or {}
        if not product:
            self.log("Polaris GraphQL returned no anonymously accessible media")
            return None

        return self._parse_media_item(product)

    def _extract_from_graphql(self, shortcode):
        """Extract using current GraphQL, with the legacy query as fallback."""
        try:
            result = self._extract_from_polaris(shortcode)
            if result and result.get('entries'):
                return result
        except RateLimitError:
            raise
        except (DownloadError, NetworkError, ValueError, TypeError, KeyError) as e:
            # A rotating token/doc-id or endpoint-specific rejection should not
            # disable the older query, which occasionally still answers.
            self.log(f"Polaris GraphQL failed: {e}")

        return self._extract_from_legacy_graphql(shortcode)

    def _extract_from_legacy_graphql(self, shortcode):
        """Extract using Instagram's older shortcode GraphQL query."""
        self.log("Trying legacy GraphQL extraction...")

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

            if data.get('errors'):
                self.log(f"GraphQL returned errors: {data['errors']}")

            # On error the envelope carries "data": null, so `.get('data', {})`
            # hands back None rather than the default - chain through `or {}`.
            media = (data.get('data') or {}).get('xdt_shortcode_media') or {}
            if media:
                self.log("Found media in GraphQL response")
                return self._parse_graphql_media(media)
            else:
                self.log("No media found in GraphQL response")
        except (RateLimitError, NetworkError, DownloadError):
            raise
        except (ValueError, TypeError, KeyError) as e:
            self.log(f"GraphQL extraction error: {e}")

        return None

    def _extract_context_json(self, webpage):
        """
        Pull the media payload out of the embed page's `contextJSON` blob.

        Current embed pages ship the GraphQL response as a JSON string embedded
        inside a JS bootstrap payload - i.e. JSON encoded twice. The older
        `__additionalDataLoaded` / `_sharedData` globals are gone, so this is the
        only path that still works on a logged-out embed.
        """
        key = '"contextJSON":'
        index = webpage.find(key)
        if index == -1:
            return None

        # The value is a JSON string literal; let the decoder handle the escaping
        # rather than trying to unpick \\\/ and \\u00253D with a regex.
        try:
            inner, _ = json.JSONDecoder().raw_decode(webpage, index + len(key))
            context = json.loads(inner)
        except (ValueError, TypeError) as e:
            self.log(f"contextJSON decode failed: {e}")
            return None

        media = (context.get('gql_data') or {}).get('shortcode_media')
        if not media:
            self.log("contextJSON contained no shortcode_media")
            return None

        return media

    def _extract_from_embed(self, shortcode):
        """Extract from embed page (last resort)"""
        self.log("Trying embed extraction...")

        embed_url = f'https://www.instagram.com/p/{shortcode}/embed/'

        try:
            webpage = self._make_request(embed_url)
            self.log(f"Embed page loaded, length: {len(webpage)} chars")

            media = self._extract_context_json(webpage)
            if media:
                self.log("Found media in contextJSON")
                return self._parse_graphql_media(media)

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
        except (RateLimitError, NetworkError, DownloadError):
            raise
        except (ValueError, TypeError, KeyError) as e:
            self.log(f"Embed extraction error: {e}")

        return None

    def _parse_media_item(self, item):
        """Parse API format media item"""
        uploader = item.get('user', {}).get('username', 'unknown')

        caption = item.get('caption') or {}
        caption_text = caption.get('text', '') if isinstance(caption, dict) else ''

        result = {
            'id': item.get('code') or self._mediaid_to_shortcode(item.get('pk', '')) or 'unknown',
            **self._caption_fields(caption_text, uploader),
            'entries': [],
            'thumbnail': None,
            'duration': item.get('video_duration'),
            'uploader': uploader,
            'type': 'image',
        }

        # A carousel wraps N children; a plain post is a single item. Handling
        # both through the same list keeps every child downloadable, including
        # mixed image+video carousels.
        carousel_media = item.get('carousel_media') or []
        children = carousel_media or [item]

        for idx, media_item in enumerate(children):
            video_versions = media_item.get('video_versions') or []

            if video_versions:
                seen_urls = set()
                formats = []
                for f_idx, video in enumerate(video_versions):
                    video_url = video.get('url')
                    if not video_url or video_url in seen_urls:
                        continue
                    seen_urls.add(video_url)
                    formats.append({
                        'url': video_url,
                        'width': video.get('width'),
                        'height': video.get('height'),
                        'format_id': f"video-{idx}-{f_idx}",
                        'has_audio': media_item.get('has_audio', True),
                    })
                result['entries'].append({
                    'kind': 'video',
                    'formats': formats,
                })
                continue

            candidates = media_item.get('image_versions2', {}).get('candidates') or []
            if candidates:
                result['entries'].append({
                    'kind': 'image',
                    'formats': [{
                        'url': image.get('url'),
                        'width': image.get('width'),
                        'height': image.get('height'),
                        'format_id': f"image-{idx}-{f_idx}",
                        'has_audio': False,
                    } for f_idx, image in enumerate(candidates)],
                })

        if carousel_media:
            result['type'] = 'carousel'
        elif result['entries']:
            result['type'] = result['entries'][0]['kind']

        # Thumbnail
        thumbnails = item.get('image_versions2', {}).get('candidates') or []
        if thumbnails:
            result['thumbnail'] = thumbnails[0].get('url')

        return finalize_info(result)

    def _parse_graphql_media(self, media):
        """Parse GraphQL format media"""
        uploader = media.get('owner', {}).get('username', 'unknown')

        edges = media.get('edge_media_to_caption', {}).get('edges') or []
        caption_text = edges[0].get('node', {}).get('text', '') if edges else ''

        result = {
            'id': media.get('shortcode', '') or 'unknown',
            **self._caption_fields(caption_text, uploader),
            'entries': [],
            'thumbnail': media.get('display_url') or media.get('thumbnail_src'),
            'duration': media.get('video_duration'),
            'uploader': uploader,
            'type': 'video' if media.get('is_video') else 'image',
        }

        sidecar = media.get('edge_sidecar_to_children', {}).get('edges') or []
        children = [edge.get('node', {}) for edge in sidecar] or [media]

        for idx, node in enumerate(children):
            dims = node.get('dimensions') or {}
            video_url = node.get('video_url')
            is_video = (
                bool(node.get('is_video'))
                or node.get('__typename') == 'GraphVideo'
            )

            if video_url:
                result['entries'].append({
                    'kind': 'video',
                    'formats': [{
                        'url': video_url,
                        'width': dims.get('width'),
                        'height': dims.get('height'),
                        'format_id': f"graphql-video-{idx}",
                        'has_audio': True,
                    }],
                })
                continue

            # Current logged-out embed payloads often expose only a reel's cover
            # image while omitting the protected video URL. Never present that
            # cover as the downloadable reel; an empty entry list makes the
            # fallback chain continue and ultimately report the login wall.
            if is_video:
                self.log("Video payload contained no playable URL")
                continue

            display_url = node.get('display_url')
            if display_url:
                result['entries'].append({
                    'kind': 'image',
                    'formats': [{
                        'url': display_url,
                        'width': dims.get('width'),
                        'height': dims.get('height'),
                        'format_id': f"graphql-image-{idx}",
                        'has_audio': False,
                    }],
                })

        if sidecar:
            result['type'] = 'carousel'

        return finalize_info(result)


class ProfilePictureExtractor(BaseExtractor):
    """Extract profile pictures"""

    def _build_result(self, username, pic_url):
        """Build the normalized info dict for a profile picture"""
        return finalize_info({
            'id': username,
            'title': f"{username}'s profile picture",
            'uploader': username,
            'type': 'profile_picture',
            'duration': None,
            'entries': [{
                'kind': 'image',
                'formats': [{
                    'url': pic_url,
                    'width': None,
                    'height': None,
                    'format_id': 'profile-pic-hd',
                    'has_audio': False,
                }],
            }],
            'thumbnail': pic_url,
        })

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

        errors = []
        for method in methods:
            try:
                result = method(username)
                if result:
                    return result
            except (RateLimitError, NetworkError, DownloadError) as e:
                self.log(f"Method failed: {e}")
                errors.append(e)
            except Exception as e:
                self.log(f"Method failed unexpectedly: {e}")
                errors.append(DownloadError(str(e)))

        for error_type in (RateLimitError, NetworkError):
            matching = [error for error in errors if isinstance(error, error_type)]
            if matching:
                raise matching[-1]

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
                pic_url = match.group(match.lastindex)
                pic_url = pic_url.replace('\\u0026', '&').replace('\\/', '/')

                return self._build_result(username, pic_url)

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
                    return self._build_result(username, pic_url)
        except (RateLimitError, NetworkError, DownloadError):
            raise
        except (ValueError, TypeError, KeyError) as e:
            self.log(f"API extraction error: {e}")

        return None
