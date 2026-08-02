# Metadata schema

The dict returned by `get_info()`, by `POST /api/info`, and by `parth-dl --json`.
This is the contract everything else in parth-dl is built on — if you are building
on top of the package, this is the page to read.

## Top level

| Field | Type | Notes |
|---|---|---|
| `id` | string | The shortcode (`Cxyz123AbCd`) for a post or reel; the **username** for a profile picture. |
| `title` | string | Caption text trimmed for display. Defaults to the first 100 characters; set `caption_max_length=None` on `InstagramDownloader` / `get_info()` for the full caption. Falls back to `"Media by <uploader>"` when there is no caption. |
| `caption` | string | Full Instagram caption text when present; empty string otherwise. Always untrimmed. |
| `uploader` | string | Username, without the `@`. `"unknown"` if it could not be determined. |
| `type` | string | One of `video`, `image`, `carousel`, `profile_picture`. |
| `duration` | number \| null | Video length in seconds. `null` for images and often for GraphQL results. |
| `thumbnail` | string \| null | Poster image URL. May be absent. |
| `entries` | array | One element per downloadable item. **This is the field you want.** |
| `formats` | array | *Legacy.* The formats of the first video entry, or `[]`. |
| `images` | array | *Legacy.* The best format of each image entry. |

A single post has one entry. A carousel has one entry per child, and those children
can mix images and videos.

> `formats` and `images` are derived from `entries` for backwards compatibility with
> code written against pre-1.0 parth-dl. New code should read `entries` — the legacy
> fields cannot represent a mixed carousel.

## `entries[]`

| Field | Type | Notes |
|---|---|---|
| `kind` | string | `video` or `image`. |
| `formats` | array | The available renditions of this one item, unsorted. |

## `entries[].formats[]`

| Field | Type | Notes |
|---|---|---|
| `url` | string | Direct CDN URL. **Short-lived and signed** — it expires, so fetch it promptly and don't store it. |
| `width` | number \| null | May genuinely be `null`; Instagram's GraphQL responses omit dimensions. |
| `height` | number \| null | Same. |
| `format_id` | string | Opaque identifier, e.g. `video-0-1`. |
| `has_audio` | boolean | `true` for API video formats, `false` for images. parth-dl prefers formats with audio. |

Pick a format with `parth_dl.utils.select_format(formats, 'best'|'worst')`, which
sorts by pixel area and copes with the `null` dimensions.

## Example — a reel

```json
{
  "id": "Cxyz123AbCd",
  "title": "sunrise over lucknow",
  "caption": "sunrise over lucknow",
  "uploader": "parthmax",
  "type": "video",
  "duration": 12.5,
  "thumbnail": "https://scontent.cdninstagram.com/.../thumb.jpg",
  "entries": [
    {
      "kind": "video",
      "formats": [
        {
          "url": "https://scontent.cdninstagram.com/.../hi.mp4",
          "width": 720,
          "height": 1280,
          "format_id": "video-0-1",
          "has_audio": true
        }
      ]
    }
  ],
  "formats": [ "... same as entries[0].formats ..." ],
  "images": []
}
```

## Example — a mixed carousel

```json
{
  "id": "Cxyz123AbCd",
  "type": "carousel",
  "uploader": "parthmax",
  "entries": [
    { "kind": "image", "formats": [ { "url": "...", "width": 1080, "height": 1080, "has_audio": false } ] },
    { "kind": "video", "formats": [ { "url": "...", "width": 720,  "height": 1280, "has_audio": true  } ] }
  ]
}
```

## Caveats worth knowing

- **The resolution Instagram advertises is not what you get.** A logged-out client is
  served a smaller transcode. parth-dl reads the real dimensions back out of the
  downloaded MP4 and reports those.
- **CDN URLs expire.** A `403`/`404` on a `url` from an older `get_info()` call means the
  signature lapsed, not that the post is gone — re-extract.
- **A profile URL yields the profile picture only.** Listing a user's posts is not
  supported; it requires authentication.
