# Web UI Usage - Local Instagram Downloader In The Browser

The parth-dl web UI is a local browser interface for downloading public Instagram reels,
posts, carousels, and profile pictures. It is served by `parth-dl serve` and runs on
your own machine.

Use the web UI when you want a paste-and-download experience without writing Python,
shell scripts, or HTTP client code.

## Start The Web UI

```bash
parth-dl serve
```

By default, parth-dl opens:

```text
http://127.0.0.1:8000
```

Downloaded files are saved to:

```text
./downloads
```

Use a custom folder:

```bash
parth-dl serve --dir ~/Videos/instagram
```

Run without opening the browser automatically:

```bash
parth-dl serve --no-open
```

## How To Download From The Web UI

1. Start the server with `parth-dl serve`.
2. Open `http://127.0.0.1:8000`.
3. Paste a public Instagram reel, post, carousel, or profile URL.
4. Choose `best` or `worst` quality.
5. Click **Download**.
6. Watch the progress card until the job finishes.
7. Use the saved path shown in the card, or click the browser download link.

The file is already saved on your machine when the job completes. The browser link
downloads another copy from the local server.

## Queue And Job Cards

The web UI keeps queued, active, completed, cancelled, and failed jobs visible.

Each job card can show:

- Instagram URL or media title
- uploader and media type
- progress percentage
- queue position
- saved file path
- browser download link
- cancel or retry action

Refreshing the browser restores recent jobs from the local server history. Job history
does not survive a server restart.

## Quality Options

| Option | Use when |
|---|---|
| `best` | You want the highest available media file. |
| `worst` | You want the smallest available media file. |

Instagram may expose only one logged-out format for some links, so both options can
produce the same result.

## Supported Links

| Link type | Web UI support |
|---|---|
| Public reel URL | Supported |
| Public post URL | Supported |
| Public carousel URL | Supported |
| Public profile URL | Downloads profile picture |
| Private account/post | Not supported |
| Story or highlight | Not supported |
| Login-only URL | Limited by Instagram's logged-out response |

## Where Files Are Saved

The server writes files to the folder selected with `--dir`.

```powershell
parth-dl serve --dir D:\Videos\Instagram
```

The UI displays the absolute save path after a job completes. If a file already exists,
parth-dl skips it by default and marks it as already downloaded.

## Cancel And Retry

- **Cancel** stops a queued job or asks a running job to stop safely.
- **Retry** creates a new job using the same URL and quality.
- Interrupted transfers may leave `.part` files that parth-dl can resume later.

## Troubleshooting

### The Web UI Does Not Open

Run:

```bash
parth-dl serve --no-open
```

Then open `http://127.0.0.1:8000` manually.

### Port 8000 Is Already In Use

Use another port:

```bash
parth-dl serve --port 9000
```

### Download Fails For A Public Reel

Some public-looking Instagram links still return a login wall to logged-out clients.
parth-dl does not use cookies or login sessions, so those links may fail until
Instagram exposes logged-out metadata again.

Try:

```bash
parth-dl -v --json "https://www.instagram.com/reel/Cxyz123AbCd/"
```

Verbose output can help identify whether Instagram returned media metadata or a login
wall.

### Browser Link Downloads A Copy

This is expected. The job already saved the file to `--dir`; the browser link is a
separate local download endpoint for convenience.

## Security

The web UI is local-first:

- Server binds to `127.0.0.1` by default.
- Non-loopback host headers are rejected.
- No permissive CORS headers are sent.
- File serving is restricted to the configured download directory.

Do not expose the web UI directly to the public internet.
