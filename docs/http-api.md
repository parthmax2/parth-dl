# Local HTTP API Usage - Instagram Downloader JSON API

`parth-dl serve` starts a local Instagram downloader API that any app can call over
HTTP. Use it when your project is written in Node.js, Go, PHP, Rust, a browser, a
desktop app, or another language, but you still want parth-dl's downloader engine.

The server also hosts the built-in web UI. For the browser interface, read
[Web UI Usage](web-ui.md).

## Start The Server

```bash
parth-dl serve
```

Default address:

```text
http://127.0.0.1:8000
```

Custom port and download folder:

```bash
parth-dl serve --port 9000 --dir ~/Videos/instagram --no-open
```

## Server Options

| Flag | Default | Description |
|---|---|---|
| `--host` | `127.0.0.1` | Loopback host. Use `127.0.0.1`, `localhost`, or `::1`. |
| `--port` | `8000` | Port for the local API and web UI. |
| `--dir` | `./downloads` | Folder where downloaded files are saved. |
| `--no-open` | off | Do not open the browser automatically. |
| `-v`, `--verbose` | off | Print verbose request and extraction logs. |

## API Flow

Most apps use this flow:

1. `POST /api/info` to validate the URL and show metadata.
2. `POST /api/download` to enqueue the download.
3. `GET /api/jobs/{id}` every few hundred milliseconds until the job finishes.
4. Read the server-side file path from `files[].path`, or fetch a browser copy from
   `files[].url`.

## Health Check

### `GET /api/health`

```bash
curl http://127.0.0.1:8000/api/health
```

Example response:

```json
{
  "ok": true,
  "version": "1.2.0",
  "download_dir": "/absolute/path/downloads"
}
```

## Get Metadata

### `POST /api/info`

Returns media metadata without downloading. The response follows the
[Metadata Schema](schema.md).

```bash
curl -X POST http://127.0.0.1:8000/api/info \
  -H "Content-Type: application/json" \
  -d "{\"url\":\"https://www.instagram.com/reel/Cxyz123AbCd/\"}"
```

A successful info response is cached briefly and reused by the next
`POST /api/download` for the same URL. This avoids extracting the same Instagram page
twice in the common preview-then-download flow.

## Start A Download

### `POST /api/download`

Starts a queued download job and returns immediately with HTTP `202`.

```bash
curl -X POST http://127.0.0.1:8000/api/download \
  -H "Content-Type: application/json" \
  -d "{\"url\":\"https://www.instagram.com/reel/Cxyz123AbCd/\",\"quality\":\"best\"}"
```

Example response:

```json
{
  "job_id": "3f9a0c2f6e214d48"
}
```

`quality` can be:

| Value | Meaning |
|---|---|
| `best` | Highest available format. This is the default. |
| `worst` | Smallest available format. Useful for previews or low storage. |

## List Recent Jobs

### `GET /api/jobs`

```bash
curl http://127.0.0.1:8000/api/jobs
```

Returns the newest queued, running, completed, cancelled, and failed jobs:

```json
{
  "jobs": [
    {
      "id": "3f9a0c2f6e214d48",
      "url": "https://www.instagram.com/reel/Cxyz123AbCd/",
      "state": "running",
      "percent": 62
    }
  ]
}
```

The server keeps a bounded history of recent jobs so the web UI can restore cards after
a refresh. History is not persisted across server restarts.

## Poll Job Progress

### `GET /api/jobs/{id}`

```bash
curl http://127.0.0.1:8000/api/jobs/3f9a0c2f6e214d48
```

Example running response:

```json
{
  "id": "3f9a0c2f6e214d48",
  "url": "https://www.instagram.com/reel/Cxyz123AbCd/",
  "quality": "best",
  "state": "running",
  "percent": 62,
  "current_item": 1,
  "total_items": 1,
  "queue_position": null,
  "message": "Downloading video",
  "files": [],
  "error": null
}
```

Possible states:

| State | Meaning |
|---|---|
| `queued` | Waiting for a worker. Check `queue_position`. |
| `running` | Download is active. Check `percent` and `message`. |
| `done` | Download finished. Check `files`. |
| `cancelled` | Job was cancelled. It can be retried. |
| `error` | Job failed. Check `error`. |

Example completed response:

```json
{
  "id": "3f9a0c2f6e214d48",
  "state": "done",
  "message": "Download complete",
  "files": [
    {
      "name": "parthmax-Cxyz123AbCd.mp4",
      "path": "/absolute/path/downloads/parthmax-Cxyz123AbCd.mp4",
      "url": "/files/parthmax-Cxyz123AbCd.mp4",
      "existing": false
    }
  ],
  "error": null
}
```

Use `files[].path` when your app runs on the same machine as the server. Use
`files[].url` when a browser needs to download a separate copy.

## Cancel A Job

### `POST /api/jobs/{id}/cancel`

```bash
curl -X POST http://127.0.0.1:8000/api/jobs/3f9a0c2f6e214d48/cancel \
  -H "Content-Type: application/json" \
  -d "{}"
```

Queued jobs cancel immediately. Running jobs cancel cooperatively. Partial `.part`
files are kept so a future download can resume when possible.

## Retry A Job

### `POST /api/jobs/{id}/retry`

```bash
curl -X POST http://127.0.0.1:8000/api/jobs/3f9a0c2f6e214d48/retry \
  -H "Content-Type: application/json" \
  -d "{}"
```

Returns a new `job_id` using the original URL and quality.

## Download A Browser Copy

### `GET /files/{name}`

```bash
curl -L -o reel.mp4 http://127.0.0.1:8000/files/parthmax-Cxyz123AbCd.mp4
```

This endpoint serves files directly inside the configured `--dir`. It cannot escape the
download directory.

## Error Responses

Errors are JSON:

```json
{
  "error": "message"
}
```

Branch on HTTP status codes instead of parsing messages.

| Status | Meaning |
|---|---|
| `400` | Bad request, malformed JSON, unsupported URL, or invalid quality. |
| `403` | Forbidden host header or unsafe file request. |
| `404` | Unknown route/job, or Instagram content is private/deleted/unsupported. |
| `429` | Instagram is throttling requests. Wait before retrying. |
| `502` | Upstream transfer failed after retries. |
| `503` | Download queue is full. Try again later. |

## Node.js Example

```js
const BASE = "http://127.0.0.1:8000";

async function request(path, options) {
  const response = await fetch(`${BASE}${path}`, options);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || `HTTP ${response.status}`);
  return body;
}

async function downloadInstagram(url) {
  const { job_id } = await request("/api/download", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, quality: "best" }),
  });

  while (true) {
    const job = await request(`/api/jobs/${job_id}`);

    if (job.state === "done") return job.files;
    if (job.state === "error") throw new Error(job.error);
    if (job.state === "cancelled") throw new Error(job.message || "cancelled");

    await new Promise((resolve) => setTimeout(resolve, 500));
  }
}
```

## Security Notes

The server is intentionally local-first:

- It binds to loopback by default.
- It rejects non-loopback `Host` headers to reduce DNS rebinding risk.
- It does not send permissive CORS headers.
- `/files/` cannot serve paths outside the download directory.
- Media redirects are validated before download.
- The queue is bounded and uses one shared rate limiter.

Do not expose `parth-dl serve` directly to the public internet. Put your own auth,
queueing, validation, and abuse controls in front of it if you build a hosted service.
