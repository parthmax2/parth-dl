"""
Tests for the download path, driven against a real local HTTP server so that
resume, truncation and Range handling are exercised for real rather than mocked.
"""

import json
import os
import shutil
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

from parth_dl.core import InstagramDownloader
from parth_dl.utils import DownloadError, ExpiredMediaError, NetworkError

PAYLOAD = bytes(range(256)) * 400  # 102,400 bytes - spans several chunks


class MediaHandler(BaseHTTPRequestHandler):
    """Serves PAYLOAD with Range support; can be told to truncate or fail."""

    truncate_after = None   # send only N bytes, then hang up
    fail_times = 0          # respond 500 this many times before succeeding
    range_supported = True
    range_offset = 0
    omit_length = False
    content_type = 'video/mp4'
    requests = []

    def log_message(self, *args):
        pass  # keep test output clean

    def do_GET(self):
        type(self).requests.append(self.headers.get('Range'))

        if type(self).fail_times > 0:
            type(self).fail_times -= 1
            self.send_error(500, "flaky")
            return

        if self.path == '/notfound':
            self.send_error(404)
            return

        start = 0
        range_header = self.headers.get('Range')
        if range_header and type(self).range_supported:
            start = int(range_header.split('=')[1].split('-')[0])
            start += type(self).range_offset

        body = PAYLOAD[start:]
        partial = start > 0 and type(self).range_supported

        self.send_response(206 if partial else 200)
        self.send_header('Content-Type', type(self).content_type)
        if not type(self).omit_length:
            self.send_header('Content-Length', str(len(body)))
        if partial:
            self.send_header('Content-Range', f'bytes {start}-{len(PAYLOAD)-1}/{len(PAYLOAD)}')
        self.end_headers()

        if type(self).truncate_after is not None:
            self.wfile.write(body[:type(self).truncate_after])
            self.close_connection = True
            return

        self.wfile.write(body)


class DownloadPathTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(('127.0.0.1', 0), MediaHandler)
        cls.port = cls.server.server_port
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        MediaHandler.truncate_after = None
        MediaHandler.fail_times = 0
        MediaHandler.range_supported = True
        MediaHandler.range_offset = 0
        MediaHandler.omit_length = False
        MediaHandler.content_type = 'video/mp4'
        MediaHandler.requests = []

        self.tmpdir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmpdir, True)

        self.downloader = InstagramDownloader(rate_limit=False, quiet=True)

        # The host allowlist exists to stop the downloader being pointed at
        # arbitrary hosts; it is covered directly in test_utils, so bypass it
        # here to let the loopback test server stand in for the CDN.
        patcher = mock.patch('parth_dl.core.validate_media_url', return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

        # Backoff would otherwise make the retry tests sleep for seconds
        sleep_patcher = mock.patch('parth_dl.utils.time.sleep')
        sleep_patcher.start()
        self.addCleanup(sleep_patcher.stop)

    def url(self, path='/video.mp4'):
        return f'http://127.0.0.1:{self.port}{path}'

    def test_downloads_complete_file(self):
        dest = self.tmpdir / 'out.mp4'
        self.downloader._download_file(self.url(), dest, show_progress=False)

        self.assertEqual(dest.read_bytes(), PAYLOAD)

    def test_creates_missing_parent_directories(self):
        dest = self.tmpdir / 'a' / 'b' / 'out.mp4'
        self.downloader._download_file(self.url(), dest, show_progress=False)

        self.assertTrue(dest.exists())

    def test_no_part_file_left_behind_on_success(self):
        dest = self.tmpdir / 'out.mp4'
        self.downloader._download_file(self.url(), dest, show_progress=False)

        self.assertFalse((self.tmpdir / 'out.mp4.part').exists())

    def test_truncated_download_does_not_produce_a_final_file(self):
        MediaHandler.truncate_after = 1024
        dest = self.tmpdir / 'out.mp4'

        with self.assertRaises(NetworkError):
            self.downloader._download_file(self.url(), dest, show_progress=False)

        # The short bytes must never be renamed into place as a "complete" file
        self.assertFalse(dest.exists())
        self.assertTrue((self.tmpdir / 'out.mp4.part').exists())

    def test_resumes_from_existing_part_file(self):
        dest = self.tmpdir / 'out.mp4'
        part = self.tmpdir / 'out.mp4.part'
        part.write_bytes(PAYLOAD[:40000])
        (self.tmpdir / 'out.mp4.part.json').write_text(
            json.dumps({'url': self.url()}), encoding='utf-8',
        )

        self.downloader._download_file(self.url(), dest, show_progress=False)

        self.assertEqual(dest.read_bytes(), PAYLOAD)
        self.assertIn('bytes=40000-', MediaHandler.requests)

    def test_restarts_untrusted_part_without_matching_metadata(self):
        dest = self.tmpdir / 'out.mp4'
        (self.tmpdir / 'out.mp4.part').write_bytes(b'unrelated bytes')

        self.downloader._download_file(self.url(), dest, show_progress=False)

        self.assertEqual(dest.read_bytes(), PAYLOAD)
        self.assertEqual(MediaHandler.requests, [None])

    def test_restarts_when_content_range_start_is_wrong(self):
        MediaHandler.range_offset = 1
        dest = self.tmpdir / 'out.mp4'
        (self.tmpdir / 'out.mp4.part').write_bytes(PAYLOAD[:40000])
        (self.tmpdir / 'out.mp4.part.json').write_text(
            json.dumps({'url': self.url()}), encoding='utf-8',
        )

        self.downloader._download_file(self.url(), dest, show_progress=False)

        self.assertEqual(dest.read_bytes(), PAYLOAD)
        self.assertEqual(MediaHandler.requests, ['bytes=40000-', None])

    def test_rejects_transfer_without_content_length(self):
        MediaHandler.omit_length = True
        dest = self.tmpdir / 'out.mp4'

        with self.assertRaises(NetworkError):
            self.downloader._download_file(self.url(), dest, show_progress=False)

        self.assertFalse(dest.exists())

    def test_rejects_text_error_page_as_media(self):
        MediaHandler.content_type = 'text/html'
        dest = self.tmpdir / 'out.mp4'

        with self.assertRaises(DownloadError):
            self.downloader._download_file(self.url(), dest, show_progress=False)

        self.assertFalse(dest.exists())

    def test_restarts_when_server_ignores_range(self):
        MediaHandler.range_supported = False
        dest = self.tmpdir / 'out.mp4'
        (self.tmpdir / 'out.mp4.part').write_bytes(PAYLOAD[:40000])

        self.downloader._download_file(self.url(), dest, show_progress=False)

        # A 200 reply resends from byte 0, so the stale prefix must be discarded
        self.assertEqual(dest.read_bytes(), PAYLOAD)

    def test_retries_transient_server_errors(self):
        MediaHandler.fail_times = 2
        dest = self.tmpdir / 'out.mp4'

        self.downloader._download_file(self.url(), dest, show_progress=False)

        self.assertEqual(dest.read_bytes(), PAYLOAD)
        self.assertEqual(len(MediaHandler.requests), 3)

    def test_does_not_retry_dead_media_url(self):
        dest = self.tmpdir / 'out.mp4'

        with self.assertRaises(DownloadError):
            self.downloader._download_file(self.url('/notfound'), dest, show_progress=False)

        # 404 means the CDN URL is gone; hammering it 5 times helps nobody
        self.assertEqual(len(MediaHandler.requests), 1)


class OutputPathTest(unittest.TestCase):
    """-o / -P handling, exercised through download() with extraction stubbed out"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmpdir, True)

        self.cwd = os.getcwd()
        os.chdir(self.tmpdir)
        self.addCleanup(os.chdir, self.cwd)

        self.downloader = InstagramDownloader(rate_limit=False, quiet=True)

        self.written = []
        patcher = mock.patch.object(
            self.downloader, '_download_file',
            side_effect=lambda url, path, **kw: (Path(path).write_bytes(b'x'),
                                                 self.written.append(Path(path)))
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def stub_info(self, info):
        patcher = mock.patch.object(self.downloader, 'get_info', return_value=info)
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def carousel(n_videos=1, n_images=1):
        entries = [
            {'kind': 'video', 'formats': [
                {'url': f'https://cdn/v{i}.mp4', 'width': 720, 'height': 1280, 'has_audio': True}]}
            for i in range(n_videos)
        ] + [
            {'kind': 'image', 'formats': [
                {'url': f'https://cdn/i{i}.jpg', 'width': 1080, 'height': 1080}]}
            for i in range(n_images)
        ]
        return {
            'id': 'ABC123', 'title': 'a post', 'uploader': 'someone',
            'type': 'carousel', 'entries': entries,
        }

    def test_mixed_carousel_downloads_every_item(self):
        self.stub_info(self.carousel(n_videos=2, n_images=2))

        self.downloader.download('https://www.instagram.com/p/ABC123/')

        # Videos and images both, not one or the other
        self.assertEqual(len(self.written), 4)
        self.assertEqual(sum(1 for p in self.written if p.suffix == '.mp4'), 2)
        self.assertEqual(sum(1 for p in self.written if p.suffix == '.jpg'), 2)

    def test_output_directory_is_created(self):
        self.stub_info(self.carousel(n_videos=1, n_images=0))
        target = self.tmpdir / 'nested' / 'dir'

        self.downloader.download('https://www.instagram.com/reel/ABC123/', output_path=str(target))

        self.assertTrue(target.is_dir())
        self.assertEqual(self.written[0].parent, target)

    def test_output_directory_applies_to_carousel(self):
        self.stub_info(self.carousel(n_videos=0, n_images=3))
        target = self.tmpdir / 'out'

        self.downloader.download('https://www.instagram.com/p/ABC123/', output_path=str(target))

        # -o used to be silently ignored for carousels, dumping files in the cwd
        for path in self.written:
            self.assertEqual(path.parent, target)

    def test_explicit_filename_is_honoured(self):
        self.stub_info(self.carousel(n_videos=1, n_images=0))

        self.downloader.download('https://www.instagram.com/reel/ABC123/',
                                 output_path=str(self.tmpdir / 'clip.mp4'))

        self.assertEqual(self.written[0].name, 'clip.mp4')

    def test_explicit_filename_is_indexed_for_carousel(self):
        self.stub_info(self.carousel(n_videos=0, n_images=2))

        self.downloader.download('https://www.instagram.com/p/ABC123/',
                                 output_path=str(self.tmpdir / 'pic.jpg'))

        self.assertEqual([p.name for p in self.written], ['pic_01.jpg', 'pic_02.jpg'])

    def test_explicit_filename_uses_real_extensions_for_mixed_carousel(self):
        self.stub_info(self.carousel(n_videos=1, n_images=1))

        self.downloader.download(
            'https://www.instagram.com/p/ABC123/',
            output_path=str(self.tmpdir / 'item.mp4'),
            output_mode='file',
        )

        self.assertEqual([p.suffix for p in self.written], ['.mp4', '.jpg'])

    def test_explicit_output_modes_do_not_guess_from_suffix(self):
        self.stub_info(self.carousel(n_videos=1, n_images=0))

        self.downloader.download(
            'https://www.instagram.com/reel/ABC123/',
            output_path='clip',
            output_mode='file',
        )
        self.assertEqual(self.written[-1], Path('clip'))

        self.downloader.download(
            'https://www.instagram.com/reel/ABC123/',
            output_path='downloads.v1',
            output_mode='directory',
        )
        self.assertEqual(self.written[-1].parent, Path('downloads.v1'))

    def test_expired_media_url_is_reextracted_once(self):
        old = self.carousel(n_videos=1, n_images=0)
        fresh = self.carousel(n_videos=1, n_images=0)
        fresh['entries'][0]['formats'][0]['url'] = 'https://cdn/fresh.mp4'
        with mock.patch.object(self.downloader, 'get_info', side_effect=[old, fresh]), \
             mock.patch.object(
                 self.downloader, '_download_file',
                 side_effect=[ExpiredMediaError('expired'), None],
             ) as transfer:
            self.downloader.download('https://www.instagram.com/reel/ABC123/')

        self.assertEqual(transfer.call_args_list[-1].args[0], 'https://cdn/fresh.mp4')

    def test_existing_files_are_skipped_unless_forced(self):
        self.stub_info(self.carousel(n_videos=1, n_images=0))
        existing = self.tmpdir / 'someone-ABC123.mp4'
        existing.write_bytes(b'already here')

        self.downloader.download('https://www.instagram.com/reel/ABC123/')

        self.assertEqual(self.written, [])
        self.assertEqual(existing.read_bytes(), b'already here')

        self.downloader.overwrite = True
        self.downloader.download('https://www.instagram.com/reel/ABC123/')

        self.assertEqual(len(self.written), 1)


if __name__ == '__main__':
    unittest.main()
