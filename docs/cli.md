# CLI reference

For local setup, testing, and contributor workflow, see
[development.md](development.md).

```bash
parth-dl [URL ...] [options]
parth-dl serve [options]
```

## Options

| Flag | Meaning |
|---|---|
| `-a`, `--batch-file FILE` | Read URLs from a file, one per line. `#` comments and blank lines are ignored. |
| `-o`, `--output PATH` | Exact output filename. Cannot be combined with `-P`, multiple URLs, or `-i`. |
| `-P`, `--paths DIR` | Directory to download into; created if missing. Cannot be combined with `-o`. |
| `-q`, `--quality {best,worst}` | Rendition to pick. Default `best`. |
| `-f`, `--force` | Overwrite existing files. Default is to skip them. |
| `-i`, `--interactive` | Keep prompting for the next URL after each download. |
| `-v`, `--verbose` | Log extraction steps and retries. |
| `--quiet` | Suppress everything except errors. |
| `--no-banner` | Don't print the banner. |
| `--list-formats` | Show every available rendition; download nothing. |
| `--json` | Print one URL's [metadata](schema.md) as one JSON document; download nothing. |
| `--no-rate-limit` | Disable rate limiting. Not recommended — this is what gets you blocked. |
| `--version` | Print the version. |

## Examples

```bash
# A reel, a post, a carousel - all the same
parth-dl https://www.instagram.com/reel/Cxyz123AbCd/

# Profile picture
parth-dl https://www.instagram.com/parthmax/

# Several at once
parth-dl https://www.instagram.com/p/AAA/ https://www.instagram.com/p/BBB/

# From a list
parth-dl -a urls.txt -P ~/Downloads/insta

# Keep going: prompts for the next URL each time
parth-dl -i

# Pipe metadata into jq
parth-dl --json https://www.instagram.com/reel/Cxyz123AbCd/ | jq -r '.entries[0].formats[0].url'
```

## Interactive mode

`-i` keeps the session open, prompting for the next URL after each download, so you
don't re-run the command for every video:

```
$ parth-dl -i

[parth-dl] Next URL (press Enter to quit) > https://www.instagram.com/reel/Cxyz123AbCd/
◆ resolving reel Cxyz123AbCd  done
◆ fetching media metadata  done
◆ downloading video
✓ saved  downloads/parthmax-Cxyz123AbCd.mp4
  video · 720x1280 · audio

1 file · 4.21 MB · 2.4s

[parth-dl] Next URL (press Enter to quit) >
```

Press Enter (or Ctrl-D) to quit. A URL that fails doesn't end the session — the failure
is still reflected in the final exit code.

Interactive mode is ignored when stdin or stdout is not a terminal, so it can never
hang a script that pipes into parth-dl. It cannot be combined with `--json` or
`--list-formats`. Use `-P` rather than `-o` in interactive mode so every URL gets
its own deterministic filename.

## Clickable links

On finishing, each saved file is printed as an OSC 8 terminal hyperlink pointing at its
`file://` URI — Ctrl/Cmd-click opens it in your video player. Terminals without OSC 8
support get the plain URI instead (most auto-linkify it anyway). Set `NO_HYPERLINKS=1`
to always print plain paths.

## Resuming

Interrupted downloads are kept as `.part` files with a small `.part.json` provenance
record and resumed on the next run. A partial is resumed only when it belongs to the
same CDN source; the returned `Content-Range` must begin at the exact expected byte.
A file is only given its final name once every byte has arrived. If any resume check
fails, parth-dl safely starts over.

## Exit codes

Branch on these from a shell script; they are a stable contract.

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | Download failed (private, deleted, unsupported) |
| `2` | Bad usage |
| `3` | Network error |
| `4` | Rate limited |
| `5` | Invalid input (not an Instagram URL) |
| `130` | Interrupted (Ctrl-C) |

```bash
if ! parth-dl "$url"; then
  case $? in
    4) echo "rate limited - backing off"; sleep 300 ;;
    5) echo "not an instagram url: $url" ;;
    *) echo "failed" ;;
  esac
fi
```

With multiple URLs, parth-dl attempts **every** URL and exits with the code of the
first failure.

## What is not supported

Stories, highlights, private accounts, and listing a user's posts. All of them require
authentication. A profile URL downloads the profile picture only.

Public reels are requested through Instagram's current logged-out Polaris flow when
the lightweight embed response contains only a cover image. This does not require
browser cookies or an Instagram login. Instagram can still rate-limit anonymous
clients; keep the default rate limiter enabled.
