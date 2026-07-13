# HTTP API

`parth-dl serve` starts a local JSON API and web UI, so **any** app — Node, Go, PHP,
Rust, a browser — can drive the downloader without shelling out or writing Python.

```bash
parth-dl serve                  # http://127.0.0.1:8000, opens your browser
parth-dl serve --port 9000 --dir ~/Videos --no-open
```

| Flag | Default | Meaning |
|---|---|---|
| `--host` | `127.0.0.1` | Interface to bind. See [Security](#security) before changing. |
| `--port` | `8000` | Port to listen on. |
| `--dir` | `./downloads` | Where files are written. |
| `--no-open` | off | Don't open a browser on start. |
| `-v` | off | Log every request. |

## Endpoints

### `GET /api/health`

```bash
curl localhost:8000/api/health
# {"ok": true, "version": "1.1.0"}
```

### `POST /api/info`

Metadata, no download. The body is the [metadata schema](schema.md).

```bash
curl -X POST localhost:8000/api/info \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://www.instagram.com/reel/Cxyz123AbCd/"}'
```

### `POST /api/download`

Starts a job and returns immediately with `202`.

```bash
curl -X POST localhost:8000/api/download \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://www.instagram.com/reel/Cxyz123AbCd/", "quality": "best"}'
# {"job_id": "3f9a...e21"}
```

`quality` is `best` (default) or `worst`.

### `GET /api/jobs/{id}`

Poll for progress.

```json
{
  "id": "3f9a...e21",
  "url": "https://www.instagram.com/reel/Cxyz123AbCd/",
  "state": "running",
  "percent": 62,
  "files": [],
  "error": null
}
```

`state` is `running`, `done`, or `error`.

- **`percent` is `-1`** when the CDN sends no `Content-Length`. Show an indeterminate
  spinner, not `0%`.
- On `done`, `files` is `[{"name": "clip.mp4", "url": "/files/clip.mp4"}]`.
- On `error`, `error` holds the message.

Job history is capped at the 100 most recent, so a long-running server can't grow
without bound. Poll and consume promptly.

### `GET /files/{name}`

Downloads a completed file. Only serves files directly inside `--dir`.

## Errors

Errors are `{"error": "message"}` with a status you can branch on — you never have to
parse the message:

| Status | Means |
|---|---|
| `400` | Bad request: not an instagram.com URL, malformed body, bad `quality`. |
| `403` | Forbidden: path traversal, or a non-loopback `Host` header. |
| `404` | Content is private, deleted, or unsupported. Also: unknown route or job. |
| `429` | Instagram is rate limiting. Back off. |
| `502` | The transfer failed upstream after retries. |

## Example: Node.js

```js
const BASE = "http://127.0.0.1:8000";

async function download(url) {
  const res = await fetch(`${BASE}/api/download`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
  if (!res.ok) throw new Error((await res.json()).error);

  const { job_id } = await res.json();

  for (;;) {
    const job = await (await fetch(`${BASE}/api/jobs/${job_id}`)).json();
    if (job.state === "done") return job.files;
    if (job.state === "error") throw new Error(job.error);
    await new Promise((r) => setTimeout(r, 400));
  }
}
```

## Security

The server **fetches URLs on your behalf**, so it is deliberately locked down:

- **Loopback only by default.** It binds `127.0.0.1`.
- **The `Host` header must be loopback.** This blocks DNS rebinding — without it, a
  website you happen to visit could point a hostname at `127.0.0.1` and drive your
  downloader.
- **No CORS header.** Cross-origin JavaScript can fire requests but cannot read the
  responses.
- **`/files/` cannot escape the download directory.**
- **Media URLs are host-allowlisted.** The downloader will only fetch from Instagram's
  own CDNs, never an arbitrary host.

Passing `--host 0.0.0.0` disables the loopback check and exposes the server to your
network — **anyone who can reach the port can then download through your IP address.**
There is no authentication. Don't do it on an untrusted network.
