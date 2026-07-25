# Recipes — using parth-dl from any app

For package setup, local testing, and contribution workflow, see
[development.md](development.md).

Three integration surfaces, in order of preference:

1. **You're in Python?** Import it — [python-api.md](python-api.md).
2. **You're not?** Run `parth-dl serve` and call the [HTTP API](http-api.md). Best for a
   long-running app: one process, no startup cost per download.
3. **One-off, or a shell script?** Shell out to `parth-dl --json` and parse stdout.
   Best for scripts and CI.

For 2 and 3, the contract is the same: **JSON on stdout, [typed exit codes](cli.md#exit-codes)
or HTTP statuses for errors.** You never parse an error message.

---

## Node.js — shelling out

```js
import { execFile } from "node:child_process";
import { promisify } from "node:util";

const run = promisify(execFile);

const EXIT = { 1: "unavailable", 2: "usage", 3: "network", 4: "rate_limited", 5: "invalid_url" };

export async function getInfo(url) {
  try {
    const { stdout } = await run("parth-dl", ["--json", url]);
    return JSON.parse(stdout);
  } catch (err) {
    throw new Error(EXIT[err.code] ?? "unknown");
  }
}

export async function download(url, dir) {
  await run("parth-dl", ["--quiet", "-P", dir, url]);
}
```

`--json` writes clean JSON to stdout — the banner is suppressed automatically when
stdout isn't a terminal, so there is nothing to strip.

## Go — shelling out

```go
func GetInfo(url string) (map[string]any, error) {
	out, err := exec.Command("parth-dl", "--json", url).Output()
	if err != nil {
		var ee *exec.ExitError
		if errors.As(err, &ee) {
			switch ee.ExitCode() {
			case 4:
				return nil, ErrRateLimited
			case 5:
				return nil, ErrInvalidURL
			}
		}
		return nil, err
	}

	var info map[string]any
	return info, json.Unmarshal(out, &info)
}
```

## PHP — over HTTP

Run `parth-dl serve` once, then:

```php
function parthdl_info(string $url): array {
    $ch = curl_init('http://127.0.0.1:8000/api/info');
    curl_setopt_array($ch, [
        CURLOPT_POST => true,
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_HTTPHEADER => ['Content-Type: application/json'],
        CURLOPT_POSTFIELDS => json_encode(['url' => $url]),
    ]);

    $body = json_decode(curl_exec($ch), true);
    $status = curl_getinfo($ch, CURLINFO_HTTP_CODE);

    if ($status !== 200) throw new RuntimeException($body['error']);
    return $body;
}
```

## Discord bot (discord.py)

```python
import discord
from parth_dl import DownloadError, InstagramDownloader

dl = InstagramDownloader(quiet=True)   # one shared rate limiter across the bot
bot = discord.Client(intents=discord.Intents.default())

@bot.event
async def on_message(message):
    if "instagram.com/reel/" not in message.content:
        return

    try:
        # download() blocks - keep it off the event loop
        path = await asyncio.to_thread(dl.download, message.content, "/tmp")
    except DownloadError as e:
        return await message.reply(f"Couldn't fetch that: {e}")

    await message.reply(file=discord.File(path))
```

`InstagramDownloader.download()` is blocking. In any async app, push it to a thread
(`asyncio.to_thread`) or a job queue, or you will stall the event loop for the length
of the transfer.

## Bash — batch with backoff

```bash
#!/usr/bin/env bash
while read -r url; do
  until parth-dl --quiet -P ./out "$url"; do
    case $? in
      4) echo "rate limited, sleeping 5m"; sleep 300 ;;   # retry
      3) echo "network hiccup, retrying"; sleep 10 ;;     # retry
      *) echo "giving up on $url"; break ;;               # permanent
    esac
  done
done < urls.txt
```

Or let parth-dl do the looping — it takes the batch file directly, attempts every URL,
and exits with the first failure's code:

```bash
parth-dl -a urls.txt -P ./out
```

---

## Things that will bite you

- **CDN URLs expire.** The `url` inside a format is signed and short-lived. Fetch it now;
  don't cache it and don't put it in a database. A `403`/`404` later means the signature
  lapsed, not that the post is gone — call `get_info()` again.
- **Keep the rate limiter on.** 30 requests/minute. Disabling it is how you get your IP
  blocked, and the block applies to your whole network.
- **Downloads are slow and blocking.** Never run one inside a web request handler.
- **A carousel returns a list of paths**, a single post returns one string. Normalise:
  `paths = r if isinstance(r, list) else [r]`.
- **Public content only.** Stories, highlights, private accounts and a user's post list
  all require authentication and are not supported.
