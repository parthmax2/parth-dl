"""Render the README CLI demo GIF from an HTML terminal mockup.

Usage:
    python scripts/render_cli_gif.py
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "cli.gif"

WIDTH = 760
HEIGHT = 500
FRAMES = 54
FRAME_MS = 65


HTML = r"""
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<style>
  :root {
    color-scheme: dark;
    --bg: #0d1117;
    --terminal: #121820;
    --terminal-2: #161d27;
    --line: #28303b;
    --text: #d9e2ee;
    --dim: #8f9baa;
    --green: #52d273;
    --orange: #ffb86b;
    --blue: #8fd3ff;
    --purple: #d7b7ff;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    width: 760px;
    height: 500px;
    display: grid;
    place-items: center;
    background: #0a0f15;
    font-family:
      ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas,
      "Liberation Mono", "Courier New", monospace;
  }
  .terminal {
    width: 720px;
    height: 468px;
    overflow: hidden;
    border: 1px solid #262f3b;
    border-radius: 10px;
    background: var(--terminal);
    box-shadow: 0 18px 45px rgba(0, 0, 0, .38);
  }
  .bar {
    height: 36px;
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 0 14px;
    background: var(--terminal-2);
    border-bottom: 1px solid #202833;
    color: var(--dim);
    font-size: 13px;
  }
  .dot {
    width: 12px;
    height: 12px;
    border-radius: 999px;
    display: inline-block;
  }
  .red { background: #ff5f57; }
  .yellow { background: #ffbd2e; }
  .green-dot { background: #28c840; }
  .title { margin-left: 10px; }
  pre {
    margin: 0;
    padding: 20px;
    color: var(--text);
    font-size: 14px;
    line-height: 1.68;
    white-space: pre-wrap;
  }
  .prompt { color: var(--green); font-weight: 700; }
  .cmd { color: #f5f7fb; font-weight: 700; }
  .brand { color: var(--purple); font-weight: 700; }
  .dim { color: var(--dim); }
  .step { color: var(--orange); font-weight: 700; }
  .ok { color: var(--green); font-weight: 700; }
  .path { color: var(--blue); font-weight: 700; }
  .rule {
    display: block;
    height: 1px;
    background: var(--line);
    margin: 10px 0 8px;
  }
  .bar-fill { color: var(--green); }
  .bar-empty { color: #2c333d; }
  .cursor {
    display: inline-block;
    width: 8px;
    height: 16px;
    margin-left: 4px;
    vertical-align: -2px;
    background: #c7d0dd;
    opacity: 0;
  }
  .cursor.on { opacity: 1; }
</style>
</head>
<body>
  <div class="terminal" id="terminal">
    <div class="bar">
      <span class="dot red"></span><span class="dot yellow"></span><span class="dot green-dot"></span>
      <span class="title">parth-dl - zsh</span>
    </div>
    <pre id="screen"></pre>
  </div>
<script>
const screen = document.getElementById("screen");

const cmd = "parth-dl https://www.instagram.com/reel/ABC123/";

function esc(text) {
  return text.replace(/[&<>]/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[ch]));
}

function progressLine(fill) {
  const total = 44;
  const done = Math.max(0, Math.min(total, Math.round(fill * total)));
  return `<span class="bar-fill">${"█".repeat(done)}</span><span class="bar-empty">${"░".repeat(total - done)}</span>`;
}

function renderFrame(frame, totalFrames) {
  const t = frame / (totalFrames - 1);
  const typedChars = Math.min(cmd.length, Math.floor(t / 0.16 * cmd.length));
  const typed = esc(cmd.slice(0, typedChars));
  const typedDone = typedChars >= cmd.length;
  const cursorOn = frame % 8 < 4 ? " on" : "";

  let html = `<span class="prompt">➜ ~</span> <span class="cmd">${typed}</span><span class="cursor${cursorOn}"></span>`;

  if (!typedDone) {
    screen.innerHTML = html;
    return;
  }

  html += `\n\n<span class="brand">parth-dl</span> <span class="dim">v1.2.0</span>\n`;
  html += `<span class="dim">Instagram Media Downloader · public content</span>\n`;
  html += `<span class="dim">Developed by Parthmax</span>\n\n`;

  if (t > 0.22) {
    html += `<span class="step">◆</span> resolving reel `;
    html += `<span class="dim">ABC123</span> <span class="ok">done</span>\n`;
  }
  if (t > 0.34) html += `<span class="step">◆</span> fetching media metadata <span class="ok">done</span>\n`;
  if (t > 0.46) {
    const p = Math.min(1, Math.max(0, (t - 0.46) / 0.32));
    const mb = (5.10 * p).toFixed(2);
    const left = p >= 0.98 ? "00:00 left" : p > 0.7 ? "00:01 left" : "00:02 left";
    html += `<span class="step">◆</span> downloading video\n`;
    html += `  ${progressLine(p)}\n`;
    html += `  <span class="dim">${mb} MB / 5.10 MB · 3.8 MB/s · ${left}</span>\n`;
  }
  if (t > 0.78) {
    html += `<span class="rule"></span>`;
    html += `<span class="ok">✓</span> saved <span class="path">downloads/parthmax-ABC123.mp4</span>\n`;
    html += `  <span class="dim">video · 720x1280 · audio</span>\n\n`;
    html += `<span class="dim">1 file · 5.10 MB · 2.1s</span>\n\n`;
    html += `<span class="prompt">➜ ~</span><span class="cursor${cursorOn}"></span>`;
  }

  screen.innerHTML = html;
}
</script>
</body>
</html>
"""


def main() -> None:
    if OUTPUT.exists():
        OUTPUT.unlink()

    frames: list[Image.Image] = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=1)
        page.set_content(HTML, wait_until="load")

        terminal = page.locator("#terminal")
        for frame in range(FRAMES):
            page.evaluate("([frame, total]) => renderFrame(frame, total)", [frame, FRAMES])
            png = terminal.screenshot(type="png")
            image = Image.open(BytesIO(png)).convert("P", palette=Image.Palette.ADAPTIVE, colors=128)
            frames.append(image)

        browser.close()

    frames[0].save(
        OUTPUT,
        save_all=True,
        append_images=frames[1:],
        duration=FRAME_MS,
        loop=0,
        optimize=True,
        disposal=2,
    )

    size_mb = OUTPUT.stat().st_size / (1024 * 1024)
    print(f"wrote {OUTPUT} ({size_mb:.2f} MB)")


if __name__ == "__main__":
    main()
