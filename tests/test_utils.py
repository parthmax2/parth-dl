"""Tests for pure helpers in parth_dl.utils"""

import io
import unittest
import urllib.request
from unittest import mock

from parth_dl.core import ValidatingRedirectHandler
from parth_dl.utils import (
    ValidationError,
    extract_instagram_id,
    extract_username,
    file_uri,
    finalize_info,
    guess_extension,
    hyperlink,
    is_media_url,
    is_profile_url,
    read_mp4_dimensions,
    sanitize_filename,
    select_format,
    style,
    validate_media_url,
    validate_url,
)


class TestUrlParsing(unittest.TestCase):

    def test_media_urls(self):
        cases = {
            'https://www.instagram.com/reel/ABC123/': 'ABC123',
            'https://www.instagram.com/p/ABC-123_x/': 'ABC-123_x',
            'https://instagram.com/tv/XYZ/?igshid=1': 'XYZ',
            'https://www.instagram.com/someone/p/ABC123/': 'ABC123',
        }
        for url, shortcode in cases.items():
            self.assertEqual(extract_instagram_id(url), shortcode, url)
            self.assertTrue(is_media_url(url))

    def test_profile_urls(self):
        self.assertEqual(extract_username('https://www.instagram.com/some.user/'), 'some.user')
        self.assertEqual(extract_username('https://www.instagram.com/@some_user'), 'some_user')
        self.assertIsNone(extract_username('https://www.instagram.com/reel/ABC123/'))

    def test_post_url_is_not_treated_as_profile(self):
        # A reel must never be routed to the profile-picture extractor
        url = 'https://www.instagram.com/reel/ABC123/'
        self.assertTrue(is_media_url(url))
        self.assertFalse(is_profile_url(url))

    def test_url_routing_is_case_insensitive(self):
        url = 'https://INSTAGRAM.COM/ReEl/ABC123/'
        validate_url(url)

        self.assertTrue(is_media_url(url))

    def test_stories_are_not_misrouted_as_posts(self):
        url = 'https://www.instagram.com/stories/someone/123456/'
        validate_url(url)

        self.assertFalse(is_media_url(url))
        self.assertFalse(is_profile_url(url))

    def test_profile_url_may_have_a_fragment(self):
        self.assertEqual(
            extract_username('https://www.instagram.com/some.user/#profile'),
            'some.user',
        )

    def test_validate_url_rejects_other_hosts(self):
        for bad in ['', 'not a url', 'https://evil.com/p/ABC/', 'javascript:alert(1)']:
            with self.assertRaises(ValidationError):
                validate_url(bad)

    def test_validate_media_url(self):
        validate_media_url('https://scontent-lhr.cdninstagram.com/v/x.mp4')
        validate_media_url('https://video.fmaa1-1.fna.fbcdn.net/v/x.mp4')

        for bad in [
            'file:///etc/passwd',                     # non-https scheme
            'http://scontent.cdninstagram.com/x.mp4',  # plaintext
            'https://evil.com/x.mp4',                  # unexpected host
            'https://cdninstagram.com.evil.com/x.mp4',  # suffix spoofing
        ]:
            with self.assertRaises(ValidationError, msg=bad):
                validate_media_url(bad)

    def test_redirect_destination_is_revalidated(self):
        handler = ValidatingRedirectHandler()
        request = urllib.request.Request('https://scontent.cdninstagram.com/x.mp4')

        with self.assertRaises(ValidationError):
            handler.redirect_request(
                request, None, 302, 'Found', {},
                'http://127.0.0.1/private',
            )


class TestFilenames(unittest.TestCase):

    def test_strips_path_separators(self):
        self.assertNotIn('/', sanitize_filename('../../etc/passwd'))
        self.assertNotIn('\\', sanitize_filename(r'..\..\windows'))

    def test_strips_emoji(self):
        self.assertEqual(sanitize_filename('my reel 🔥🔥'), 'my_reel')

    def test_windows_reserved_names(self):
        self.assertEqual(sanitize_filename('CON'), 'CON_')
        self.assertEqual(sanitize_filename('nul'), 'nul_')

    def test_empty_input(self):
        self.assertEqual(sanitize_filename(''), 'untitled')
        self.assertEqual(sanitize_filename('...'), 'untitled')

    def test_length_cap(self):
        self.assertLessEqual(len(sanitize_filename('a' * 500)), 100)


class TestExtensions(unittest.TestCase):

    def test_from_url(self):
        self.assertEqual(guess_extension('https://cdn/x/video.mp4?a=1', 'video'), '.mp4')
        self.assertEqual(guess_extension('https://cdn/x/pic.webp', 'image'), '.webp')

    def test_fallback_to_kind(self):
        self.assertEqual(guess_extension('https://cdn/x/opaque', 'video'), '.mp4')
        self.assertEqual(guess_extension('', 'image'), '.jpg')


class TestFormatSelection(unittest.TestCase):

    def test_picks_by_area(self):
        formats = [
            {'url': 'lo', 'width': 640, 'height': 360},
            {'url': 'hi', 'width': 1080, 'height': 1920},
        ]
        self.assertEqual(select_format(formats, 'best')['url'], 'hi')
        self.assertEqual(select_format(formats, 'worst')['url'], 'lo')

    def test_null_dimensions_do_not_crash(self):
        # Instagram's GraphQL responses really do contain "width": null
        formats = [
            {'url': 'unknown', 'width': None, 'height': None},
            {'url': 'known', 'width': 720, 'height': 1280},
        ]
        self.assertEqual(select_format(formats, 'best')['url'], 'known')
        self.assertEqual(select_format(formats, 'worst')['url'], 'unknown')

    def test_skips_formats_without_url(self):
        self.assertIsNone(select_format([{'width': 1, 'height': 1}], 'best'))
        self.assertIsNone(select_format([], 'best'))


class TestMp4Dimensions(unittest.TestCase):
    """The video track header is the only trustworthy source of the real size"""

    def build_mp4(self, width, height, audio_first=True):
        import struct

        def box(kind, payload):
            return struct.pack('>I4s', len(payload) + 8, kind) + payload

        def tkhd(w, h):
            # version/flags + v0 fixed fields + reserved/layer/volume + matrix
            payload = b'\x00' * 4 + b'\x00' * 20 + b'\x00' * 16 + b'\x00' * 36
            return box(b'tkhd', payload + struct.pack('>II', w << 16, h << 16))

        audio_trak = box(b'trak', tkhd(0, 0))       # audio tracks carry 0x0
        video_trak = box(b'trak', tkhd(width, height))
        traks = (audio_trak + video_trak) if audio_first else (video_trak + audio_trak)

        return box(b'ftyp', b'isom' + b'\x00' * 8) + box(b'moov', traks)

    def test_reads_video_track_dimensions(self):
        import os
        import tempfile

        for audio_first in (True, False):
            fd, path = tempfile.mkstemp(suffix='.mp4')
            with os.fdopen(fd, 'wb') as f:
                f.write(self.build_mp4(720, 1280, audio_first=audio_first))

            try:
                # The 0x0 audio track must not be mistaken for the video track
                self.assertEqual(read_mp4_dimensions(path), (720, 1280))
            finally:
                os.unlink(path)

    def test_non_mp4_returns_none(self):
        import os
        import tempfile

        fd, path = tempfile.mkstemp()
        with os.fdopen(fd, 'wb') as f:
            f.write(b'this is not an mp4')

        try:
            self.assertIsNone(read_mp4_dimensions(path))
        finally:
            os.unlink(path)

    def test_missing_file_returns_none(self):
        self.assertIsNone(read_mp4_dimensions('does-not-exist.mp4'))


class TestFinalizeInfo(unittest.TestCase):

    def test_legacy_keys_are_derived_from_entries(self):
        info = finalize_info({
            'entries': [
                {'kind': 'image', 'formats': [
                    {'url': 'small', 'width': 100, 'height': 100},
                    {'url': 'large', 'width': 800, 'height': 800},
                ]},
                {'kind': 'video', 'formats': [{'url': 'v', 'width': 720, 'height': 1280}]},
            ],
        })
        self.assertEqual([i['url'] for i in info['images']], ['large'])
        self.assertEqual([f['url'] for f in info['formats']], ['v'])


class TestHyperlinks(unittest.TestCase):

    @staticmethod
    def stream(isatty):
        s = io.StringIO()
        s.isatty = lambda: isatty
        return s

    def test_tty_gets_an_osc8_escape(self):
        with mock.patch.dict('os.environ', {'WT_SESSION': '1'}, clear=False):
            out = hyperlink('label', 'https://example.com', self.stream(True))

        self.assertIn('\033]8;;https://example.com', out)
        self.assertIn('label', out)

    def test_pipe_gets_a_bare_url(self):
        # Escapes must never reach a pipe - they would corrupt piped output
        out = hyperlink('label', 'https://example.com', self.stream(False))

        self.assertEqual(out, 'https://example.com')
        self.assertNotIn('\033', out)

    def test_no_hyperlinks_env_var_is_honoured(self):
        with mock.patch.dict('os.environ', {'NO_HYPERLINKS': '1'}, clear=False):
            out = hyperlink('label', 'https://example.com', self.stream(True))

        self.assertNotIn('\033', out)

    def test_file_uri_is_absolute(self):
        uri = file_uri('out.mp4')

        self.assertTrue(uri.startswith('file:///'))
        self.assertTrue(uri.endswith('out.mp4'))

    def test_no_color_disables_ansi_styling(self):
        stream = self.stream(True)
        with mock.patch.dict('os.environ', {'NO_COLOR': '1'}, clear=False):
            self.assertEqual(style('done', 'green', stream=stream), 'done')

    def test_non_tty_never_gets_ansi_styling(self):
        self.assertEqual(style('done', 'green', stream=self.stream(False)), 'done')


if __name__ == '__main__':
    unittest.main()
