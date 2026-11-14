"""Record a run as a time-lapse: python -m fogline.viewer.timelapse runs/<name> --out docs/media/<name>

It serves the run on a free local port, opens the viewer headless (software WebGL), steps through
every saved year, takes a screenshot of each once that year's turn and feed have loaded, and joins
them with ffmpeg into an MP4 and a small GIF for the README. It only reads the run.

Needs the `record` extras (Playwright for Python) and ffmpeg on the PATH. It uses an installed
Chromium rather than downloading one: --chromium, or the newest in the Playwright cache.
"""

import argparse
import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

VIEWPORT = {"width": 1600, "height": 900}
GL_FLAGS = ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]
SETTLE_MS = 400   # after a year's text has loaded, time for the scene to draw it
GIF_WIDTH = 960


def browser_caches() -> list[Path]:
    """Where Playwright keeps its browsers: its own setting, then the Windows and Linux defaults."""
    places = [os.environ.get("PLAYWRIGHT_BROWSERS_PATH"), os.environ.get("LOCALAPPDATA") and
              str(Path(os.environ["LOCALAPPDATA"]) / "ms-playwright"), str(Path.home() / ".cache" / "ms-playwright")]
    return [Path(place) for place in places if place]


# Installed browsers, tried when Playwright's cache can't be seen (a packaged app's terminal may get
# its own view of AppData, without the cache).
INSTALLED = (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
             r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
             "/usr/bin/google-chrome", "/usr/bin/chromium")


def cached_chromium() -> Path | None:
    """The newest Chromium in Playwright's cache, on Windows or Linux, or else an installed Chrome or Edge."""
    for cache in browser_caches():
        found = sorted(cache.glob("chromium-*/chrome-win64/chrome.exe")) + sorted(cache.glob("chromium-*/chrome-linux*/chrome"))
        if found:
            return found[-1]
    return next((Path(p) for p in INSTALLED if Path(p).exists()), None)


def mp4_command(frames: Path, fps: int, out: Path) -> list[str]:
    return ["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps), "-i", str(frames / "f%05d.png"),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", str(out)]


def gif_command(frames: Path, fps: int, out: Path) -> list[str]:
    graph = (f"fps={fps},scale={GIF_WIDTH}:-1:flags=lanczos,split[a][b];"
             "[a]palettegen=max_colors=128[p];[b][p]paletteuse=dither=bayer:bayer_scale=4")
    return ["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps), "-i", str(frames / "f%05d.png"),
            "-vf", graph, str(out)]


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _serve(runs_dir: Path, port: int):
    import uvicorn
    from fogline.viewer.app import create_app
    server = uvicorn.Server(uvicorn.Config(create_app(runs_dir), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            return server
        time.sleep(0.1)
    raise RuntimeError("the viewer server did not start")


def record(folder: Path, out: Path, fps: int, chromium: Path | None) -> tuple[Path, Path, int]:
    from playwright.sync_api import sync_playwright
    browser_path = chromium or cached_chromium()
    if browser_path is None or not browser_path.exists():
        looked = ", ".join([*map(str, browser_caches()), *INSTALLED])
        raise FileNotFoundError(f"no Chromium found in {looked}; pass --chromium with the path to chrome")
    if shutil.which("ffmpeg") is None:
        raise FileNotFoundError("ffmpeg is not on the PATH")
    port = _free_port()
    server = _serve(folder.parent, port)
    base = f"http://127.0.0.1:{port}"
    with urllib.request.urlopen(f"{base}/api/runs/{folder.name}") as answer:
        ticks = [frame["tick"] for frame in json.load(answer)["frames"]]
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as scratch, sync_playwright() as play:
        frames = Path(scratch)
        browser = play.chromium.launch(executable_path=str(browser_path), headless=True, args=GL_FLAGS)
        # The viewer's CSP forbids eval, which Playwright's wait checks use; this browser only loads our
        # own local page, so the recording context alone sets the CSP aside.
        page = browser.new_context(viewport=VIEWPORT, bypass_csp=True).new_page()
        errors: list[str] = []
        page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
        page.goto(f"{base}/?run={folder.name}&record")
        page.wait_for_function("document.getElementById('scrub').max > 0", timeout=120_000)
        for index, tick in enumerate(ticks):
            page.evaluate("(i) => { const s = document.getElementById('scrub'); s.value = String(i);"
                          " s.dispatchEvent(new Event('input')); }", index)
            try:
                page.wait_for_function(
                    "(tick) => document.getElementById('when').textContent.endsWith(`tick ${tick}`)"
                    " && !document.getElementById('turn-sub').textContent.startsWith('Reading')"
                    " && document.getElementById('feed').children.length > 0", arg=tick, timeout=60_000)
            except Exception as error:   # say what the page showed, so a stuck wait can be read
                shown = page.evaluate("() => ({when: document.getElementById('when').textContent,"
                                      " turn: document.getElementById('turn-sub').textContent,"
                                      " feed: document.getElementById('feed').children.length,"
                                      " status: document.getElementById('status').textContent,"
                                      " readout: document.getElementById('readout').textContent})")
                page.screenshot(path=str(out.with_suffix(".stuck.png")))
                raise RuntimeError(f"year {index} (tick {tick}) never finished loading: {shown}; console: {errors[-3:]}") from error
            page.wait_for_timeout(SETTLE_MS)
            page.screenshot(path=str(frames / f"f{index + 1:05d}.png"))
        browser.close()
        mp4, gif = out.with_suffix(".mp4"), out.with_suffix(".gif")
        subprocess.run(mp4_command(frames, fps, mp4), check=True)
        subprocess.run(gif_command(frames, fps, gif), check=True)
    server.should_exit = True
    return mp4, gif, len(ticks)


def main() -> None:
    parser = argparse.ArgumentParser(description="Record a Fogline run as an MP4 and a GIF time-lapse.")
    parser.add_argument("folder", type=Path, help="a run folder, for example runs/p4-mix-s3")
    parser.add_argument("--out", type=Path, help="output path without extension (default: docs/media/<run name>)")
    parser.add_argument("--fps", type=int, default=6, help="saved years per second of film (default 6)")
    parser.add_argument("--chromium", type=Path, help="path to a Chromium or Chrome executable")
    args = parser.parse_args()
    folder = args.folder.resolve()
    if not (folder / "manifest.json").is_file():
        parser.error(f"{folder} is not a run folder (no manifest.json)")
    try:
        mp4, gif, count = record(folder, args.out or Path("docs/media") / folder.name, args.fps, args.chromium)
    except (FileNotFoundError, RuntimeError, subprocess.CalledProcessError, urllib.error.URLError) as error:
        parser.error(str(error))
    print(f"{count} years recorded: {mp4} and {gif}")


if __name__ == "__main__":
    main()
