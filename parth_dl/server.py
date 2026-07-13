"""
Local HTTP server + web UI for parth-dl (`parth-dl serve`).

Exposes the downloader as a small JSON API so that any app - in any language -
can drive it, and serves the bundled single-page UI that talks to that API.

Standard library only, like the rest of the package.
"""

import argparse
import json
import mimetypes
import threading
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from . import __version__
from .core import InstagramDownloader
from .utils import (
    DownloadError,
    NetworkError,
    RateLimitError,
    ValidationError,
    symbols,
)

WEB_ROOT = Path(__file__).parent / 'web'

# A request body is a URL and a quality string; anything larger is not ours.
MAX_BODY_BYTES = 8 * 1024

# Hosts a browser may legitimately use to reach a loopback-bound server.
LOOPBACK_HOSTS = {'127.0.0.1', 'localhost', '::1', '[::1]'}

# Map the downloader's exception hierarchy onto HTTP status codes, so a caller
# in any language can branch on the status instead of parsing messages.
ERROR_STATUS = [
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

    def create(self, url):
        job_id = uuid.uuid4().hex
        with self._lock:
            self._jobs[job_id] = {
                'id': job_id,
                'url': url,
                'state': 'running',
                'percent': 0,
                'files': [],
                'error': None,
            }
            self._order.append(job_id)

            # Bound the history so a long-lived server cannot grow without limit
            while len(self._order) > self.MAX_JOBS:
                self._jobs.pop(self._order.pop(0), None)

        return job_id

    def update(self, job_id, **fields):
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job.update(fields)

    def get(self, job_id):
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None


class DownloadService:
    """Runs downloads on worker threads and reports progress into a JobStore"""

    def __init__(self, download_dir, verbose=False):
        self.download_dir = Path(download_dir).resolve()
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.verbose = verbose
        self.jobs = JobStore()

    def get_info(self, url):
        return InstagramDownloader(verbose=self.verbose, quiet=True).get_info(url)

    def start_download(self, url, quality='best'):
        job_id = self.jobs.create(url)
        thread = threading.Thread(
            target=self._run, args=(job_id, url, quality), daemon=True
        )
        thread.start()
        return job_id

    def _run(self, job_id, url, quality):
        def on_progress(downloaded, total):
            # `total` is 0 when the CDN sends no Content-Length; report -1 so the
            # UI can show an indeterminate bar rather than a bogus 0%.
            percent = round(downloaded / total * 100) if total else -1
            self.jobs.update(job_id, percent=percent)

        try:
            downloader = InstagramDownloader(
                verbose=self.verbose, quiet=True, progress_hook=on_progress,
            )
            result = downloader.download(
                url, output_path=str(self.download_dir), quality=quality,
            )

            # download() returns a bare path for a single item, a list for a carousel
            paths = result if isinstance(result, list) else [result]
            files = [
                {'name': Path(p).name, 'url': f'/files/{Path(p).name}'}
                for p in paths
            ]
            self.jobs.update(job_id, state='done', percent=100, files=files)

        except Exception as e:
            self.jobs.update(
                job_id, state='error', error=str(e), status=status_for(e),
            )

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
        length = int(self.headers.get('Content-Length') or 0)
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
            return self._send_json({'ok': True, 'version': __version__})

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

        url = payload.get('url')
        if not url or not isinstance(url, str):
            return self._error(400, 'Missing "url"')

        if path == '/api/info':
            return self._post_info(url)

        if path == '/api/download':
            quality = payload.get('quality', 'best')
            if quality not in ('best', 'worst'):
                return self._error(400, 'quality must be "best" or "worst"')
            return self._send_json(
                {'job_id': self.service.start_download(url, quality)}, status=202
            )

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
    service = DownloadService(download_dir, verbose=verbose)

    is_loopback = host in LOOPBACK_HOSTS

    handler = type('BoundHandler', (Handler,), {
        'service': service,
        'enforce_loopback': is_loopback,
    })

    httpd = ThreadingHTTPServer((host, port), handler)
    httpd.verbose = verbose
    httpd.daemon_threads = True

    url = f'http://{host if is_loopback else host}:{httpd.server_port}/'

    print(f"\n{sym['ok']} parth-dl web UI  ->  {url}")
    print(f"  Downloads: {service.download_dir}")
    if not is_loopback:
        print(f"\n{sym['warn']} Bound to {host}, not loopback: anyone who can reach this "
              f"port can download through your IP address.")
    print("\nPress Ctrl+C to stop.\n")

    if open_browser:
        threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print(f"\n{sym['ok']} Stopped.")
    finally:
        httpd.server_close()

    return 0
