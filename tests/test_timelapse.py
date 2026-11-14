"""The time-lapse recorder's pure parts: finding a browser and the ffmpeg commands. Recording itself
needs a browser and ffmpeg, so it is run by hand, not in CI."""

from pathlib import Path

from fogline.viewer import timelapse


def test_the_newest_cached_chromium_is_used(tmp_path, monkeypatch):
    for version in ("chromium-1100", "chromium-1200"):
        exe = tmp_path / version / "chrome-linux" / "chrome"
        exe.parent.mkdir(parents=True)
        exe.write_text("")
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
    assert timelapse.cached_chromium() == tmp_path / "chromium-1200" / "chrome-linux" / "chrome"


def test_with_no_cache_it_falls_back_to_an_installed_browser_or_none(tmp_path, monkeypatch):
    monkeypatch.setattr(timelapse, "browser_caches", lambda: [tmp_path])
    monkeypatch.setattr(timelapse, "INSTALLED", (str(tmp_path / "missing"),))
    assert timelapse.cached_chromium() is None
    installed = tmp_path / "chrome.exe"
    installed.write_text("")
    monkeypatch.setattr(timelapse, "INSTALLED", (str(tmp_path / "missing"), str(installed)))
    assert timelapse.cached_chromium() == installed


def test_the_mp4_is_even_sized_h264_from_numbered_frames():
    command = timelapse.mp4_command(Path("frames"), 6, Path("out.mp4"))
    assert command[0] == "ffmpeg" and command[-1] == "out.mp4"
    assert command[command.index("-framerate") + 1] == "6"
    assert command[command.index("-i") + 1] == str(Path("frames") / "f%05d.png")
    assert "libx264" in command and "yuv420p" in command
    assert "trunc(iw/2)*2" in command[command.index("-vf") + 1]


def test_the_gif_uses_one_palette_at_the_readme_width():
    graph = timelapse.gif_command(Path("frames"), 4, Path("out.gif"))
    vf = graph[graph.index("-vf") + 1]
    assert vf.startswith("fps=4,") and f"scale={timelapse.GIF_WIDTH}:-1" in vf
    assert "palettegen" in vf and "paletteuse" in vf
