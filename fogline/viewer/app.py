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

from fogline import messages, pricing, snapshot, view
from fogline import run as run_module
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
    return {"ticks": manifest["ticks"], "played_to": _last_tick(folder / "turns.jsonl"),
            "frames": [view.frame(snapshot.load(p)) for p in newer]}


FEED_TEXT = 240  # characters of a message or note shown in the feed

def _goods(goods: dict) -> str:
    return ", ".join(f"{n} {good.replace('blueprint:', 'the blueprint for ')}" for good, n in sorted(goods.items())) or "nothing"


def _line(action: dict) -> tuple[str, str] | None:
    """What one carried-out action looks like in the feed: (kind, plain words), or None for the
    routine ones (moving units, setting workers) that would drown the rest."""
    kind = action.get("kind")
    if kind == "send_message":
        return kind, f"to {action.get('to')}: {messages.harden(Config(), str(action.get('text', '')))[:FEED_TEXT]}"
    if kind == "offer_trade":
        return kind, f"offered {action.get('to')} {_goods(action.get('give') or {})} for {_goods(action.get('get') or {})}"
    if kind == "respond_trade":
        return kind, f"{'accepted' if action.get('accept') else 'turned down'} offer {action.get('offer')}"
    if kind == "build":
        return kind, f"began a {str(action.get('building', '')).replace('_', ' ')}"
    if kind == "train_unit":
        return kind, f"trained a {action.get('unit_kind')}"
    if kind == "set_research":
        return kind, f"set scholars on {str(action.get('tech', '')).replace('_', ' ')}"
    if kind == "set_note":
        return kind, f"noted: {messages.harden(Config(), str(action.get('text', '')))[:FEED_TEXT]}"
    return None


def activity(folder: Path, until: int, limit: int) -> list[dict]:
    """The latest things rulers actually did, at or before a tick, newest first: every action a
    turn sent that no rejection names, and every first contact a turn was woken by. Agent text
    is hardened as a receiver would see it; the page shows it with textContent."""
    config, items = Config(), []
    for record in _lines(folder / "turns.jsonl"):
        reply = record.get("reply")
        if record["step"] != "decide" or record["tick"] > until or not isinstance(reply, dict):
            continue
        name = config.civ(record["civ"]).name
        for trigger in (record.get("observation") or {}).get("triggers", []):
            if trigger.get("trigger") == "contact":
                items.append({"tick": record["tick"], "civ": record["civ"], "kind": "contact",
                              "text": f"{name} met {trigger.get('detail')}", "to": trigger.get("detail")})
        refused = {r.get("index") for r in record.get("rejections") or []}
        for index, action in enumerate(reply.get("actions") or []):
            line = _line(action) if isinstance(action, dict) and index not in refused else None
            if line:
                items.append({"tick": record["tick"], "civ": record["civ"], "kind": line[0],
                              "text": f"{name} {line[1]}", "to": action.get("to")})
    return items[::-1][:limit]


def ruler_cost(folder: Path, until: int) -> dict[str, dict]:
    """Calls made per civ up to and including a tick, and what they cost at list prices
    (fogline/pricing.py), not the figure `claude -p` reported."""
    ruled = run_module.manifest_models(json.loads((folder / "manifest.json").read_text(encoding="ascii"))) \
        if (folder / "manifest.json").is_file() else {}
    spent: dict[str, dict] = {}
    for row in _lines(folder / "outputs.jsonl"):
        if row["tick"] > until:
            continue
        civ = spent.setdefault(row["civ"], {"calls": 0, "cost_usd": 0.0})
        civ["calls"] += 1
        civ["cost_usd"] += pricing.row_cost(row, ruled.get(row["civ"], pricing.DEFAULT_MODEL))
    return {civ: {**v, "cost_usd": round(v["cost_usd"], 2)} for civ, v in sorted(spent.items())}


def _last_tick(path: Path) -> int | None:
    """The tick of the last whole line of a turn log, read from its end so a long log costs nothing."""
    if not path.is_file():
        return None
    with open(path, "rb") as handle:
        handle.seek(0, 2)
        handle.seek(max(0, handle.tell() - 65536))
        lines = handle.read().splitlines()
    for line in reversed(lines):
        try:
            return json.loads(line)["tick"]
        except (ValueError, KeyError):
            continue
    return None


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
        return [{"name": name, "updated": folder.stat().st_mtime,  # the viewer opens on the newest
                 **json.loads((folder / "manifest.json").read_text(encoding="ascii"))}
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

    @app.get("/api/runs/{name}/activity")
    def run_activity(name: str, until: int, limit: int = 40) -> list[dict]:
        folder = list_runs(runs_dir).get(name)
        if folder is None:
            raise HTTPException(404, "No run with that name.")
        return activity(folder, until, max(1, min(limit, 200)))

    @app.get("/api/runs/{name}/cost")
    def run_cost(name: str, until: int) -> dict:
        folder = list_runs(runs_dir).get(name)
        if folder is None:
            raise HTTPException(404, "No run with that name.")
        return ruler_cost(folder, until)

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
