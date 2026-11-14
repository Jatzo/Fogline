"""Local web server for the read-only map: python -m fogline.viewer --runs runs

It reads run folders written by fogline.run and never runs the engine. A run name from a
request is only used to look up a folder already found by listing, so no request text
reaches a path.
"""

import json
import mimetypes
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.staticfiles import StaticFiles

from fogline import messages, snapshot, view
from fogline.config import Config

STATIC = Path(__file__).parent / "static"
RUN_NAME = re.compile(r"[A-Za-z0-9_-]+")
SNAPSHOT_NAME = re.compile(r"snap-(\d{5})\.json\.gz")
CSP = "default-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
# Windows can map .js to text/plain in its registry, and a browser refuses a module served that way.
mimetypes.add_type("text/javascript", ".js")


def list_runs(runs_dir: Path) -> dict[str, Path]:
    """Real folders (not links) under runs_dir that hold a manifest, by name."""
    if not runs_dir.is_dir():
        return {}
    found = {}
    for entry in sorted(runs_dir.iterdir()):
        if (RUN_NAME.fullmatch(entry.name) and entry.is_dir() and not entry.is_symlink()
                and not entry.is_junction() and (entry / "manifest.json").is_file()):
            found[entry.name] = entry
    return found


def frames_after(folder: Path, after: int) -> dict:
    """Only the frames saved after a tick, so a viewer following a run reads the new snapshots
    and not the whole run again. The manifest says how many ticks the run will reach."""
    manifest = json.loads((folder / "manifest.json").read_text(encoding="ascii"))
    newer = sorted(p for p in folder.iterdir()
                   if (m := SNAPSHOT_NAME.fullmatch(p.name)) and int(m.group(1)) > after)
    return {"ticks": manifest["ticks"], "frames": [view.frame(snapshot.load(p)) for p in newer]}


def load_run(folder: Path) -> dict:
    manifest = json.loads((folder / "manifest.json").read_text(encoding="ascii"))
    paths = sorted(p for p in folder.iterdir() if SNAPSHOT_NAME.fullmatch(p.name))
    states = [snapshot.load(p) for p in paths]
    if not states:
        raise HTTPException(404, "This run has no snapshots.")
    return {"manifest": manifest, "world": view.world(Config(), states[0]),
            "frames": [view.frame(state) for state in states]}


def create_app(runs_dir: Path) -> FastAPI:
    app = FastAPI(title="Fogline viewer", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-cache"  # always revalidate, so an edited page is never stale
        return response

    @app.get("/api/runs")
    def runs() -> list[dict]:
        return [{"name": name, **json.loads((folder / "manifest.json").read_text(encoding="ascii"))}
                for name, folder in list_runs(runs_dir).items()]

    @app.get("/api/runs/{name}")
    def run(name: str) -> dict:
        folder = list_runs(runs_dir).get(name)
        if folder is None:
            raise HTTPException(404, "No run with that name.")
        return load_run(folder)

    @app.get("/api/runs/{name}/frames")
    def frames(name: str, after: int) -> dict:
        folder = list_runs(runs_dir).get(name)
        if folder is None:
            raise HTTPException(404, "No run with that name.")
        return frames_after(folder, after)

    @app.get("/api/runs/{name}/turns")
    def turns(name: str, civ: str, tick: int) -> dict:
        folder = list_runs(runs_dir).get(name)
        if folder is None:
            raise HTTPException(404, "No run with that name.")
        return civ_turn(folder, civ, tick)

    app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
    return app


def _lines(path: Path) -> list[dict]:
    """A JSON-lines log. A run still being played may be half way through writing its last line,
    so a last line that doesn't parse is left out; one anywhere else is a real fault."""
    if not path.is_file():
        return []
    with open(path, encoding="utf-8") as handle:
        lines = [line for line in handle if line.strip()]
    rows = []
    for number, line in enumerate(lines):
        try:
            rows.append(json.loads(line))
        except ValueError:
            if number < len(lines) - 1:
                raise
    return rows


def civ_turn(folder: Path, civ: str, tick: int) -> dict:
    """The civ's latest turn and latest reflection at or before tick, with the stored output for
    each when the run kept outputs. civ and tick are only compared with records, never used as paths."""
    mine = [r for r in _lines(folder / "turns.jsonl") if r["civ"] == civ and r["tick"] <= tick]
    outputs = {(r["tick"], r["civ"], r["step"]): r for r in _lines(folder / "outputs.jsonl") if r["civ"] == civ}
    found: dict = {"civ": civ, "tick": tick}
    for step in ("decide", "reflect"):
        record = max((r for r in mine if r["step"] == step), key=lambda r: r["tick"], default=None)
        output = outputs.get((record["tick"], civ, step)) if record else None
        found[step] = record and {**record, "output": output and {"status": output["status"], "raw": output["raw"]}}
    seen = (found["decide"] or {}).get("observation") or {}
    found["messages"] = [{**m, "body": messages.unwrap(m["text"])} for m in seen.get("messages", [])]
    return found
