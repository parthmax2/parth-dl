"""
Local HTTP server + web UI for parth-dl (`parth-dl serve`).

Exposes the downloader as a small JSON API so that any app - in any language -
can drive it, and serves the bundled single-page UI that talks to that API.

Standard library only, like the rest of the package.
"""

import argparse
import json
import mimetypes
import queue
import socket
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

from . import __version__
from .core import InstagramDownloader
from .utils import (
    DownloadError,
    NetworkError,
    RateLimiter,
    RateLimitError,
    ValidationError,
    symbols,
)

WEB_ROOT = Path(__file__).parent / 'web'

# A request body is a URL and a quality string; anything larger is not ours.
MAX_BODY_BYTES = 8 * 1024

# Hosts a browser may legitimately use to reach a loopback-bound server.
LOOPBACK_HOSTS = {'127.0.0.1', 'localhost', '::1', '[::1]'}


class ServiceBusyError(DownloadError):
    """Raised when the bounded local download queue is full."""


class JobCancelledError(DownloadError):
    """Raised cooperatively when a running job is cancelled."""


# Map the downloader's exception hierarchy onto HTTP status codes, so a caller
# in any language can branch on the status instead of parsing messages.
ERROR_STATUS = [
    (ServiceBusyError, 503),
    (ValidationError, 400),
    (RateLimitError, 429),
    (NetworkError, 502),
    (DownloadError, 404),
]


def status_for(exc):
    for exc_type, status in ERROR_STATUS:
        if isinstance(exc, exc_type):
            return status
    return 500


class JobStore:
    """Thread-safe record of in-flight and finished download jobs"""

    MAX_JOBS = 100

    def __init__(self):
        self._jobs = {}
        self._order = []
        self._lock = threading.Lock()

    def create(self, url, quality='best', media=None):
        job_id = uuid.uuid4().hex
        with self._lock:
            self._jobs[job_id] = {
                'id': job_id,
                'url': url,
                'quality': quality,
                'state': 'queued',
                'queue_position': None,
                'percent': 0,
                'current_item': 0,
                'total_items': len((media or {}).get('entries') or []),
                'files': [],
                'error': None,
                'message': 'Queued',
                'media': self._media_summary(media),
                'created_at': time.time(),
            }
            self._order.append(job_id)
            self._trim_locked()

        return job_id

    @staticmethod
    def _media_summary(info):
        if not info:
            return None
        return {
            'title': info.get('title'),
            'uploader': info.get('uploader'),
            'type': info.get('type'),
            'thumbnail': info.get('thumbnail'),
            'item_count': len(info.get('entries') or []),
        }

    def update(self, job_id, **fields):
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job.update(fields)
                self._trim_locked()

    def _trim_locked(self):
        """Evict old finished jobs without losing work that is still running."""
        while len(self._order) > self.MAX_JOBS:
            removable = next(
                (job_id for job_id in self._order
                 if self._jobs[job_id]['state'] not in ('queued', 'running')),
                None,
            )
            if removable is None:
                break
            self._order.remove(removable)
            self._jobs.pop(removable, None)

    def get(self, job_id):
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def list(self):
        """Return newest-first snapshots for restoring the UI after refresh."""
        with self._lock:
            return [
                dict(self._jobs[job_id])
                for job_id in reversed(self._order)
                if job_id in self._jobs
            ]


class DownloadService:
    """Runs downloads on worker threads and reports progress into a JobStore"""

    MAX_PENDING = 25
    INFO_CACHE_SECONDS = 120

    def __init__(self, download_dir, verbose=False):
        self.download_dir = Path(download_dir).resolve()
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.verbose = verbose
        self.jobs = JobStore()
        self.rate_limiter = RateLimiter(max_requests=30, time_window=60)
        self._queue = queue.Queue()
        self._worker = None
        self._worker_lock = threading.Lock()
        self._closed = False
        self._pending_ids = []
        self._cancel_events = {}
        self._cancelled_ids = set()
        self._info_cache = {}
        self._cache_lock = threading.Lock()

    def get_info(self, url):
        info = InstagramDownloader(
            verbose=self.verbose, quiet=True, rate_limiter=self.rate_limiter,
        ).get_info(url)
        self._cache_info(url, info)
        return info

    def _cache_info(self, url, info):
        with self._cache_lock:
            self._info_cache[url] = (time.monotonic(), info)
            if len(self._info_cache) > JobStore.MAX_JOBS:
                oldest = min(
                    self._info_cache,
                    key=lambda key: self._info_cache[key][0],
                )
                self._info_cache.pop(oldest, None)

    def _cached_info(self, url):
        with self._cache_lock:
            cached = self._info_cache.get(url)
            if not cached:
                return None
            created, info = cached
            if time.monotonic() - created > self.INFO_CACHE_SECONDS:
                self._info_cache.pop(url, None)
                return None
            return info

    def start_download(self, url, quality='best'):
        with self._worker_lock:
            if self._closed:
                raise ServiceBusyError("Download service is stopping")
            if len(self._pending_ids) >= self.MAX_PENDING:
                raise ServiceBusyError("Download queue is full; try again later")
            if self._worker is None:
                self._worker = threading.Thread(
                    target=self._worker_loop, name='parth-dl-worker', daemon=True,
                )
                self._worker.start()

            info = self._cached_info(url)
            job_id = self.jobs.create(url, quality=quality, media=info)
            self._cancel_events[job_id] = threading.Event()
            self._pending_ids.append(job_id)
            self._refresh_queue_positions_locked()
            self._queue.put_nowait((job_id, url, quality, info))
        return job_id

    def _refresh_queue_positions_locked(self):
        for position, job_id in enumerate(self._pending_ids, 1):
            self.jobs.update(
                job_id, queue_position=position,
                message=f'Queued (position {position})',
            )

    def _worker_loop(self):
        while True:
            task = self._queue.get()
            try:
                if task is None:
                    return
                job_id = task[0]
                with self._worker_lock:
                    if job_id in self._pending_ids:
                        self._pending_ids.remove(job_id)
                    self._refresh_queue_positions_locked()
                    if job_id in self._cancelled_ids:
                        self._cancelled_ids.remove(job_id)
                        self._cancel_events.pop(job_id, None)
                        continue
                    self.jobs.update(
                        job_id, state='running', queue_position=None,
                        message='Preparing download',
                    )
                self._run(*task)
            finally:
                self._queue.task_done()

    def _run(self, job_id, url, quality, info=None):
        cancel_event = self._cancel_events[job_id]
        downloader = None

        def on_progress(downloaded, total):
            if cancel_event.is_set():
                raise JobCancelledError("Cancelled by user")

            item = downloader.progress_item_index
            count = max(downloader.progress_item_count, 1)
            if total:
                item_fraction = min(downloaded / total, 1)
                percent = round(((item - 1) + item_fraction) / count * 100)
            else:
                percent = -1
            self.jobs.update(
                job_id, percent=percent, current_item=item,
                total_items=count, message=f'Downloading item {item} of {count}',
            )

        try:
            downloader = InstagramDownloader(
                verbose=self.verbose, quiet=True, progress_hook=on_progress,
                rate_limiter=self.rate_limiter,
            )

            total_items = len((info or {}).get('entries') or [])
            if info is not None:
                self.jobs.update(
                    job_id, media=JobStore._media_summary(info),
                    total_items=total_items,
                )

            if cancel_event.is_set():
                raise JobCancelledError("Cancelled by user")

            download_kwargs = {
                'output_path': str(self.download_dir),
                'quality': quality,
            }
            if info is not None:
                download_kwargs['info'] = info
            result = downloader.download(url, **download_kwargs)

            if info is None and downloader.last_info is not None:
                info = downloader.last_info
                self._cache_info(url, info)
                total_items = len(info.get('entries') or [])
                self.jobs.update(
                    job_id, media=JobStore._media_summary(info),
                    total_items=total_items,
                )

            new_paths = result if isinstance(result, list) else [result]
            skipped_paths = downloader.last_skipped_files
            existing = {str(Path(path).resolve()) for path in skipped_paths}
            paths = new_paths + skipped_paths
            files = [
                {
                    'name': Path(path).name,
                    'url': f'/files/{quote(Path(path).name)}',
                    'path': str(Path(path).resolve()),
                    'existing': str(Path(path).resolve()) in existing,
                }
                for path in paths
            ]
            if not new_paths and skipped_paths:
                message = 'Already downloaded'
            elif skipped_paths:
                message = (
                    f'Saved {len(new_paths)} new; '
                    f'{len(skipped_paths)} already existed'
                )
            else:
                message = f'Saved {len(new_paths)} file(s)'
            self.jobs.update(
                job_id, state='done', percent=100, files=files,
                message=message, current_item=total_items,
            )

        except JobCancelledError:
            self.jobs.update(
                job_id, state='cancelled', error=None,
                message='Cancelled; partial download kept for resume',
            )
        except Exception as e:
            self.jobs.update(
                job_id, state='error', error=str(e), status=status_for(e),
                message='Download failed',
            )
        finally:
            self._cancel_events.pop(job_id, None)

    def cancel(self, job_id):
        with self._worker_lock:
            job = self.jobs.get(job_id)
            if not job:
                raise ValidationError("No such job")

            if job['state'] == 'queued':
                self._cancel_events[job_id].set()
                self._cancelled_ids.add(job_id)
                if job_id in self._pending_ids:
                    self._pending_ids.remove(job_id)
                self.jobs.update(
                    job_id, state='cancelled', queue_position=None,
                    message='Cancelled before download started',
                )
                self._refresh_queue_positions_locked()
            elif job['state'] == 'running':
                self._cancel_events[job_id].set()
                self.jobs.update(
                    job_id, cancel_requested=True, message='Cancelling…',
                )

            return self.jobs.get(job_id)

    def retry(self, job_id):
        job = self.jobs.get(job_id)
        if not job:
            raise ValidationError("No such job")
        if job['state'] not in ('error', 'cancelled'):
            raise ValidationError("Only failed or cancelled jobs can be retried")
        return self.start_download(job['url'], job.get('quality', 'best'))

    def close(self, wait=True):
        """Stop the bounded worker and release its resources."""
        with self._worker_lock:
            if self._closed:
                return
            self._closed = True
            worker = self._worker

            if not wait:
                while True:
                    try:
                        task = self._queue.get_nowait()
                    except queue.Empty:
                        break
                    if task is not None:
                        job_id = task[0]
                        self.jobs.update(
                            job_id, state='cancelled', error=None,
                            message='Server stopped before download started',
                        )
                        if job_id in self._pending_ids:
                            self._pending_ids.remove(job_id)
                        self._cancel_events.pop(job_id, None)
                        self._cancelled_ids.discard(job_id)
                    self._queue.task_done()
                self._refresh_queue_positions_locked()

            if worker is not None:
                self._queue.put_nowait(None)

        if wait:
            self._queue.join()
            if worker is not None:
                worker.join()

    def resolve_file(self, name):
        """
        Resolve a download-directory file by name, or None if it escapes the
        directory. Guards against `/files/../../etc/passwd`.
        """
        candidate = (self.download_dir / name).resolve()

        if candidate.parent != self.download_dir or not candidate.is_file():
            return None

        return candidate


class Handler(BaseHTTPRequestHandler):

    server_version = f'parth-dl/{__version__}'
    protocol_version = 'HTTP/1.1'

    service = None          # injected by serve()
    enforce_loopback = True

    def log_message(self, *args):
        if self.server.verbose:
            super().log_message(*args)

    # -- helpers ----------------------------------------------------------

    def _send_json(self, payload, status=200):
        body = json.dumps(payload).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        # Deliberately no Access-Control-Allow-Origin: without it a page on
        # another origin can fire requests but never read the responses.
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status, message):
        self._send_json({'error': message}, status=status)

    def _read_json(self):
        try:
            length = int(self.headers.get('Content-Length') or 0)
        except (TypeError, ValueError):
            return None
        if length <= 0 or length > MAX_BODY_BYTES:
            return None
        try:
            return json.loads(self.rfile.read(length))
        except (ValueError, UnicodeDecodeError):
            return None

    def _host_allowed(self):
        """
        Reject requests whose Host header is not loopback.

        Without this, any website the user happens to visit could point a
        hostname at 127.0.0.1 (DNS rebinding) and drive their downloader.
        """
        if not self.enforce_loopback:
            return True

        host = (self.headers.get('Host') or '').rsplit(':', 1)[0]
        return host in LOOPBACK_HOSTS

    # -- routes -----------------------------------------------------------

    def do_GET(self):
        if not self._host_allowed():
            return self._error(403, 'Forbidden host')

        path = urlparse(self.path).path

        if path in ('/', '/index.html'):
            return self._serve_ui()

        if path == '/api/health':
            return self._send_json({
                'ok': True,
                'version': __version__,
                'download_dir': str(self.service.download_dir),
            })

        if path == '/api/jobs':
            return self._send_json({'jobs': self.service.jobs.list()})

        if path.startswith('/api/jobs/'):
            return self._get_job(path[len('/api/jobs/'):])

        if path.startswith('/files/'):
            return self._serve_file(unquote(path[len('/files/'):]))

        self._error(404, 'Not found')

    def do_POST(self):
        if not self._host_allowed():
            return self._error(403, 'Forbidden host')

        path = urlparse(self.path).path
        payload = self._read_json()

        if payload is None or not isinstance(payload, dict):
            return self._error(400, 'Expected a JSON object body')

        if path.startswith('/api/jobs/'):
            parts = path.strip('/').split('/')
            if len(parts) == 4 and parts[3] == 'cancel':
                return self._post_cancel(parts[2])
            if len(parts) == 4 and parts[3] == 'retry':
                return self._post_retry(parts[2])
            return self._error(404, 'Not found')

        url = payload.get('url')
        if not url or not isinstance(url, str):
            return self._error(400, 'Missing "url"')

        if path == '/api/info':
            return self._post_info(url)

        if path == '/api/download':
            quality = payload.get('quality', 'best')
            if quality not in ('best', 'worst'):
                return self._error(400, 'quality must be "best" or "worst"')
            try:
                job_id = self.service.start_download(url, quality)
            except ServiceBusyError as e:
                return self._error(503, str(e))
            return self._send_json({'job_id': job_id}, status=202)

        self._error(404, 'Not found')

    def _post_info(self, url):
        try:
            return self._send_json(self.service.get_info(url))
        except Exception as e:
            return self._error(status_for(e), str(e))

    def _get_job(self, job_id):
        job = self.service.jobs.get(job_id)
        if not job:
            return self._error(404, 'No such job')
        return self._send_json(job)

    def _post_cancel(self, job_id):
        try:
            return self._send_json(self.service.cancel(job_id))
        except ValidationError as e:
            return self._error(404 if str(e) == 'No such job' else 409, str(e))

    def _post_retry(self, job_id):
        try:
            new_job_id = self.service.retry(job_id)
            return self._send_json({'job_id': new_job_id}, status=202)
        except ServiceBusyError as e:
            return self._error(503, str(e))
        except ValidationError as e:
            return self._error(404 if str(e) == 'No such job' else 409, str(e))

    def _serve_ui(self):
        index = WEB_ROOT / 'index.html'
        if not index.is_file():
            return self._error(500, 'Web UI is missing from this install')

        body = index.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_file(self, name):
        path = self.service.resolve_file(name)
        if not path:
            return self._error(403, 'Forbidden')

        content_type = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
        size = path.stat().st_size

        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(size))
        self.send_header('Content-Disposition', f'attachment; filename="{path.name}"')
        self.end_headers()

        with open(path, 'rb') as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)


def create_serve_parser():
    parser = argparse.ArgumentParser(
        prog='parth-dl serve',
        description='Serve the parth-dl web UI and JSON API on localhost',
    )
    parser.add_argument('--host', default='127.0.0.1',
                        help='Interface to bind (default: 127.0.0.1, loopback only)')
    parser.add_argument('--port', type=int, default=8000,
                        help='Port to listen on (default: 8000)')
    parser.add_argument('--dir', default='downloads',
                        help='Directory to download into (default: ./downloads)')
    parser.add_argument('--no-open', action='store_true',
                        help='Do not open a browser window on start')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Log every request')
    return parser


def serve(host='127.0.0.1', port=8000, download_dir='downloads',
          open_browser=True, verbose=False):
    """Run the web UI / JSON API until interrupted. Returns a process exit code."""
    sym = symbols()

    is_loopback = host in {'127.0.0.1', 'localhost', '::1'}
    if not is_loopback:
        raise ValidationError(
            "The web UI is local-only; --host must be 127.0.0.1, localhost, or ::1"
        )

    service = DownloadService(download_dir, verbose=verbose)

    handler = type('BoundHandler', (Handler,), {
        'service': service,
        'enforce_loopback': True,
    })

    server_class = ThreadingHTTPServer
    if ':' in host:
        server_class = type(
            'IPv6ThreadingHTTPServer',
            (ThreadingHTTPServer,),
            {'address_family': socket.AF_INET6},
        )

    try:
        httpd = server_class((host, port), handler)
    except Exception:
        service.close(wait=False)
        raise
    httpd.verbose = verbose
    httpd.daemon_threads = True

    display_host = f'[{host}]' if ':' in host else host
    url = f'http://{display_host}:{httpd.server_port}/'

    print(f"\n{sym['ok']} parth-dl web UI  ->  {url}")
    print(f"  Downloads: {service.download_dir}")
    print("\nPress Ctrl+C to stop.\n")

    if open_browser:
        threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print(f"\n{sym['ok']} Stopped.")
    finally:
        httpd.server_close()
        service.close(wait=False)

    return 0
