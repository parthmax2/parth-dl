"""
Tests for `parth-dl serve` - the JSON API that non-Python callers build on.

Driven against a real server on a loopback port, so the routing, the status-code
contract and the path/host guards are exercised end to end rather than mocked.
"""

import io
import json
import shutil
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from parth_dl import __version__
from parth_dl.server import DownloadService, Handler, ServiceBusyError, serve
from parth_dl.utils import DownloadError, NetworkError, RateLimitError, ValidationError


class ServerTestCase(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmpdir, True)

        self.service = DownloadService(self.tmpdir / 'downloads')
        self.addCleanup(self.service.close)

        handler = type('BoundHandler', (Handler,), {'service': self.service})
        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        self.httpd.verbose = False
        self.httpd.daemon_threads = True

        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

        self.port = self.httpd.server_port

    # -- helpers ----------------------------------------------------------

    def request(self, path, method='GET', body=None, headers=None):
        """Returns (status, parsed_body_or_bytes)"""
        url = f'http://127.0.0.1:{self.port}{path}'
        data = json.dumps(body).encode() if body is not None else None

        req = urllib.request.Request(
            url, data=data, method=method,
            headers={'Content-Type': 'application/json', **(headers or {})},
        )

        try:
            with urllib.request.urlopen(req) as r:
                return r.status, self._decode(r)
        except urllib.error.HTTPError as e:
            return e.code, self._decode(e)

    @staticmethod
    def _decode(response):
        raw = response.read()
        if 'json' in (response.headers.get('Content-Type') or ''):
            return json.loads(raw)
        return raw

    def wait_for_job(self, job_id, timeout=5):
        deadline = time.time() + timeout
        while time.time() < deadline:
            _, job = self.request(f'/api/jobs/{job_id}')
            if job['state'] in ('done', 'error', 'cancelled'):
                return job
            time.sleep(0.02)
        self.fail(f'job {job_id} never finished')

    def wait_for_state(self, job_id, expected, timeout=5):
        deadline = time.time() + timeout
        while time.time() < deadline:
            job = self.service.jobs.get(job_id)
            if job['state'] == expected:
                return job
            time.sleep(0.01)
        self.fail(f'job {job_id} never reached {expected}')


class RoutingTest(ServerTestCase):

    def test_health(self):
        status, body = self.request('/api/health')

        self.assertEqual(status, 200)
        self.assertEqual(body['ok'], True)
        self.assertEqual(body['version'], __version__)
        self.assertEqual(body['download_dir'], str(self.service.download_dir))

    def test_index_serves_the_ui(self):
        status, body = self.request('/')

        self.assertEqual(status, 200)
        self.assertIn(b'parth-dl', body)

    def test_unknown_route_is_404(self):
        self.assertEqual(self.request('/nope')[0], 404)

    def test_unknown_job_is_404(self):
        self.assertEqual(self.request('/api/jobs/deadbeef')[0], 404)


class InfoTest(ServerTestCase):

    def test_returns_the_metadata_dict(self):
        info = {'id': 'Cxyz', 'uploader': 'parthmax_', 'type': 'video', 'entries': []}

        with mock.patch.object(DownloadService, 'get_info', return_value=info):
            status, body = self.request(
                '/api/info', 'POST', {'url': 'https://www.instagram.com/reel/Cxyz123AbCd/'})

        self.assertEqual(status, 200)
        self.assertEqual(body, info)

    def test_exception_types_map_onto_status_codes(self):
        # This mapping is the error contract for callers who are not in Python
        cases = [
            (ValidationError('bad url'), 400),
            (RateLimitError('slow down'), 429),
            (NetworkError('upstream died'), 502),
            (DownloadError('private'), 404),
        ]

        for exc, expected in cases:
            with self.subTest(exc=type(exc).__name__):
                with mock.patch.object(DownloadService, 'get_info', side_effect=exc):
                    status, body = self.request(
                        '/api/info', 'POST',
                        {'url': 'https://www.instagram.com/reel/Cxyz123AbCd/'})

                self.assertEqual(status, expected)
                self.assertEqual(body['error'], str(exc))

    def test_missing_url_is_rejected(self):
        status, body = self.request('/api/info', 'POST', {})

        self.assertEqual(status, 400)
        self.assertIn('url', body['error'])

    def test_non_object_body_is_rejected(self):
        self.assertEqual(self.request('/api/info', 'POST', ['not', 'an', 'object'])[0], 400)


class DownloadJobTest(ServerTestCase):

    def test_job_runs_to_completion_and_exposes_the_file(self):
        target = self.service.download_dir / 'clip.mp4'

        def fake_download(self_, url, output_path=None, quality='best'):
            Path(target).write_bytes(b'video-bytes')
            return str(target)

        with mock.patch('parth_dl.server.InstagramDownloader.download', fake_download):
            status, body = self.request(
                '/api/download', 'POST',
                {'url': 'https://www.instagram.com/reel/Cxyz123AbCd/'})

            self.assertEqual(status, 202)
            job = self.wait_for_job(body['job_id'])

        self.assertEqual(job['state'], 'done')
        self.assertEqual(job['percent'], 100)
        self.assertEqual(job['files'][0]['name'], 'clip.mp4')
        self.assertEqual(job['files'][0]['url'], '/files/clip.mp4')
        self.assertEqual(job['files'][0]['path'], str(target.resolve()))
        self.assertFalse(job['files'][0]['existing'])

        # ...and the file is actually retrievable through the URL it advertises
        status, content = self.request(job['files'][0]['url'])
        self.assertEqual(status, 200)
        self.assertEqual(content, b'video-bytes')

    def test_carousel_reports_every_file(self):
        paths = []
        for name in ('a.jpg', 'b.jpg'):
            path = self.service.download_dir / name
            path.write_bytes(b'x')
            paths.append(str(path))

        with mock.patch('parth_dl.server.InstagramDownloader.download', return_value=paths):
            _, body = self.request(
                '/api/download', 'POST', {'url': 'https://www.instagram.com/p/Cxyz123AbCd/'})
            job = self.wait_for_job(body['job_id'])

        self.assertEqual([f['name'] for f in job['files']], ['a.jpg', 'b.jpg'])

    def test_failed_job_reports_the_error(self):
        with mock.patch('parth_dl.server.InstagramDownloader.download',
                        side_effect=DownloadError('content is private')):
            _, body = self.request(
                '/api/download', 'POST', {'url': 'https://www.instagram.com/p/Cxyz123AbCd/'})
            job = self.wait_for_job(body['job_id'])

        self.assertEqual(job['state'], 'error')
        self.assertEqual(job['error'], 'content is private')

    def test_bad_quality_is_rejected(self):
        status, body = self.request(
            '/api/download', 'POST',
            {'url': 'https://www.instagram.com/p/Cxyz123AbCd/', 'quality': 'ultra'})

        self.assertEqual(status, 400)
        self.assertIn('quality', body['error'])

    def test_progress_hook_drives_the_percentage(self):
        """The percent the UI polls comes from the downloader's progress hook"""
        seen = []

        def fake_download(self_, url, output_path=None, quality='best'):
            # Stand in for _download_file streaming chunks off the CDN
            self_.progress_hook(25, 100)
            seen.append(self.service.jobs.get(job_id)['percent'])
            self_.progress_hook(100, 100)
            seen.append(self.service.jobs.get(job_id)['percent'])
            return str(self.service.download_dir / 'x.mp4')

        with mock.patch('parth_dl.server.InstagramDownloader.download', fake_download):
            job_id = self.service.start_download('https://www.instagram.com/reel/Cxyz123AbCd/')
            self.wait_for_job(job_id)

        self.assertEqual(seen, [25, 100])

    def test_unknown_content_length_reports_indeterminate_progress(self):
        # total=0 means the CDN sent no Content-Length. Reporting 0% would look
        # like a stalled download, so the API says -1 and the UI shows a
        # indeterminate bar instead.
        def fake_download(self_, url, output_path=None, quality='best'):
            self_.progress_hook(500, 0)
            seen.append(self.service.jobs.get(job_id)['percent'])
            return str(self.service.download_dir / 'x.mp4')

        seen = []
        with mock.patch('parth_dl.server.InstagramDownloader.download', fake_download):
            job_id = self.service.start_download('https://www.instagram.com/reel/Cxyz123AbCd/')
            self.wait_for_job(job_id)

        self.assertEqual(seen, [-1])

    def test_download_jobs_run_through_a_single_worker_queue(self):
        gate = threading.Event()
        lock = threading.Lock()
        active = 0
        maximum = 0

        def fake_download(self_, url, output_path=None, quality='best'):
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
            gate.wait(2)
            with lock:
                active -= 1
            return str(self.service.download_dir / f'{url[-2]}.mp4')

        with mock.patch('parth_dl.server.InstagramDownloader.download', fake_download):
            first = self.service.start_download('https://www.instagram.com/p/A/')
            second = self.service.start_download('https://www.instagram.com/p/B/')
            time.sleep(0.05)
            self.assertEqual(maximum, 1)
            gate.set()
            self.wait_for_job(first)
            self.wait_for_job(second)

        self.assertEqual(maximum, 1)

    def test_queue_capacity_is_bounded(self):
        self.service._pending_ids = [
            f'occupied-{index}' for index in range(self.service.MAX_PENDING)
        ]

        with self.assertRaises(ServiceBusyError):
            self.service.start_download('https://www.instagram.com/p/A/')

    def test_jobs_share_one_rate_limiter(self):
        with mock.patch('parth_dl.server.InstagramDownloader') as downloader:
            downloader.return_value.get_info.return_value = {'id': 'x'}
            self.service.get_info('https://www.instagram.com/p/A/')

        self.assertIs(
            downloader.call_args.kwargs['rate_limiter'],
            self.service.rate_limiter,
        )

    def test_info_result_is_reused_by_the_following_download(self):
        url = 'https://www.instagram.com/p/A/'
        info = {
            'id': 'A', 'title': 'cached', 'uploader': 'user', 'type': 'image',
            'thumbnail': None,
            'entries': [{'kind': 'image', 'formats': [{'url': 'https://cdn/a.jpg'}]}],
        }
        seen = []

        def fake_download(self_, url_, output_path=None, quality='best', info=None):
            seen.append(info)
            return str(self.service.download_dir / 'a.jpg')

        with mock.patch(
            'parth_dl.server.InstagramDownloader.get_info', return_value=info,
        ) as extract, mock.patch(
            'parth_dl.server.InstagramDownloader.download', fake_download,
        ):
            self.service.get_info(url)
            job_id = self.service.start_download(url)
            self.wait_for_job(job_id)

        self.assertEqual(extract.call_count, 1)
        self.assertIs(seen[0], info)

    def test_queued_job_exposes_position_then_runs(self):
        gate = threading.Event()

        def fake_download(self_, url, output_path=None, quality='best'):
            gate.wait(2)
            return str(self.service.download_dir / 'x.mp4')

        with mock.patch('parth_dl.server.InstagramDownloader.download', fake_download):
            first = self.service.start_download('https://www.instagram.com/p/A/')
            self.wait_for_state(first, 'running')
            second = self.service.start_download('https://www.instagram.com/p/B/')

            queued = self.service.jobs.get(second)
            self.assertEqual(queued['state'], 'queued')
            self.assertEqual(queued['queue_position'], 1)

            gate.set()
            self.wait_for_job(first)
            self.wait_for_job(second)

    def test_carousel_progress_is_aggregate_and_never_resets(self):
        seen = []

        def fake_download(self_, url, output_path=None, quality='best'):
            self_.progress_item_count = 2
            self_.progress_item_index = 1
            self_.progress_hook(100, 100)
            seen.append(self.service.jobs.get(job_id)['percent'])
            self_.progress_item_index = 2
            self_.progress_hook(50, 100)
            seen.append(self.service.jobs.get(job_id)['percent'])
            return str(self.service.download_dir / 'x.mp4')

        with mock.patch('parth_dl.server.InstagramDownloader.download', fake_download):
            job_id = self.service.start_download('https://www.instagram.com/p/A/')
            self.wait_for_job(job_id)

        self.assertEqual(seen, [50, 75])

    def test_queued_job_can_be_cancelled(self):
        gate = threading.Event()
        calls = []

        def fake_download(self_, url, output_path=None, quality='best'):
            calls.append(url)
            gate.wait(2)
            return str(self.service.download_dir / 'x.mp4')

        with mock.patch('parth_dl.server.InstagramDownloader.download', fake_download):
            first = self.service.start_download('https://www.instagram.com/p/A/')
            self.wait_for_state(first, 'running')
            second = self.service.start_download('https://www.instagram.com/p/B/')

            cancelled = self.service.cancel(second)
            self.assertEqual(cancelled['state'], 'cancelled')
            gate.set()
            self.wait_for_job(first)
            self.wait_for_job(second)

        self.assertEqual(len(calls), 1)

    def test_running_job_can_be_cancelled_and_retried(self):
        gate = threading.Event()
        entered = threading.Event()
        attempts = 0

        def fake_download(self_, url, output_path=None, quality='best'):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                entered.set()
                gate.wait(2)
                self_.progress_hook(1, 100)
            return str(self.service.download_dir / 'x.mp4')

        with mock.patch('parth_dl.server.InstagramDownloader.download', fake_download):
            first = self.service.start_download('https://www.instagram.com/p/A/')
            self.assertTrue(entered.wait(2))
            self.service.cancel(first)
            gate.set()
            cancelled = self.wait_for_job(first)
            self.assertEqual(cancelled['state'], 'cancelled')

            retried = self.service.retry(first)
            completed = self.wait_for_job(retried)

        self.assertEqual(completed['state'], 'done')
        self.assertEqual(attempts, 2)

    def test_existing_file_is_reported_as_already_downloaded(self):
        target = self.service.download_dir / 'existing.mp4'
        target.write_bytes(b'already here')

        def fake_download(self_, url, output_path=None, quality='best'):
            self_.last_skipped_files = [str(target)]
            return []

        with mock.patch('parth_dl.server.InstagramDownloader.download', fake_download):
            job_id = self.service.start_download('https://www.instagram.com/p/A/')
            job = self.wait_for_job(job_id)

        self.assertEqual(job['message'], 'Already downloaded')
        self.assertTrue(job['files'][0]['existing'])
        self.assertEqual(job['files'][0]['path'], str(target.resolve()))

    def test_recent_jobs_endpoint_restores_history(self):
        target = self.service.download_dir / 'x.mp4'

        with mock.patch(
            'parth_dl.server.InstagramDownloader.download', return_value=str(target),
        ):
            _, body = self.request(
                '/api/download', 'POST',
                {'url': 'https://www.instagram.com/p/A/'},
            )
            self.wait_for_job(body['job_id'])

        status, history = self.request('/api/jobs')
        self.assertEqual(status, 200)
        self.assertEqual(history['jobs'][0]['id'], body['job_id'])

    def test_cancel_and_retry_http_endpoints(self):
        gate = threading.Event()
        entered = threading.Event()

        def fake_download(self_, url, output_path=None, quality='best'):
            if url.endswith('/A/'):
                entered.set()
                gate.wait(2)
            return str(self.service.download_dir / 'x.mp4')

        with mock.patch('parth_dl.server.InstagramDownloader.download', fake_download):
            first = self.service.start_download('https://www.instagram.com/p/A/')
            self.assertTrue(entered.wait(2))
            _, queued = self.request(
                '/api/download', 'POST',
                {'url': 'https://www.instagram.com/p/B/'},
            )

            status, cancelled = self.request(
                f"/api/jobs/{queued['job_id']}/cancel", 'POST', {},
            )
            self.assertEqual(status, 200)
            self.assertEqual(cancelled['state'], 'cancelled')

            status, retried = self.request(
                f"/api/jobs/{queued['job_id']}/retry", 'POST', {},
            )
            self.assertEqual(status, 202)

            gate.set()
            self.wait_for_job(first)
            completed = self.wait_for_job(retried['job_id'])

        self.assertEqual(completed['state'], 'done')


class SecurityTest(ServerTestCase):

    def test_path_traversal_is_blocked(self):
        secret = self.tmpdir / 'secret.txt'
        secret.write_text('do not serve me')

        for attack in ['/files/../secret.txt',
                       '/files/..%2fsecret.txt',
                       '/files/%2e%2e%2fsecret.txt',
                       '/files/subdir/../../secret.txt']:
            with self.subTest(attack=attack):
                status, body = self.request(attack)

                self.assertIn(status, (403, 404))
                self.assertNotIn(b'do not serve me', body if isinstance(body, bytes) else b'')

    def test_non_loopback_host_header_is_rejected(self):
        # Cheap DNS-rebinding defence: a site the user visits must not be able to
        # point a hostname at 127.0.0.1 and drive their downloader.
        status, _ = self.request('/api/health', headers={'Host': 'evil.com'})

        self.assertEqual(status, 403)

    def test_loopback_host_headers_are_accepted(self):
        for host in ['127.0.0.1', 'localhost', f'localhost:{self.port}']:
            with self.subTest(host=host):
                self.assertEqual(self.request('/api/health', headers={'Host': host})[0], 200)

    def test_no_cors_header_is_advertised(self):
        # Without ACAO, cross-origin JS can fire requests but never read replies
        url = f'http://127.0.0.1:{self.port}/api/health'
        with urllib.request.urlopen(url) as r:
            self.assertIsNone(r.headers.get('Access-Control-Allow-Origin'))

    def test_oversized_body_is_rejected(self):
        status, _ = self.request('/api/info', 'POST', {'url': 'x' * 20000})

        self.assertEqual(status, 400)

    def test_malformed_content_length_is_rejected(self):
        handler = object.__new__(Handler)
        handler.headers = {'Content-Length': 'not-a-number'}
        handler.rfile = io.BytesIO(b'{}')

        self.assertIsNone(handler._read_json())

    def test_remote_binding_is_rejected(self):
        with self.assertRaises(ValidationError):
            serve(
                host='0.0.0.0',
                download_dir=self.tmpdir / 'remote',
                open_browser=False,
            )


class JobStoreTest(ServerTestCase):

    def test_history_is_bounded(self):
        store = self.service.jobs
        first = store.create('url-0')
        store.update(first, state='done')

        for i in range(store.MAX_JOBS + 5):
            job_id = store.create(f'url-{i}')
            store.update(job_id, state='done')

        # The oldest jobs are evicted, so a long-lived server cannot grow forever
        self.assertIsNone(store.get(first))

    def test_running_jobs_are_never_evicted(self):
        store = self.service.jobs
        running = store.create('still-running')

        for i in range(store.MAX_JOBS + 5):
            job_id = store.create(f'done-{i}')
            store.update(job_id, state='done')

        self.assertIsNotNone(store.get(running))


if __name__ == '__main__':
    unittest.main()
