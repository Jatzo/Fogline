"""The read-only viewer (PLAN section 12, Phase 1): frames, the local API and the page's text sinks."""

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fogline import messages, run, snapshot, view, worldgen
from fogline.config import Config
from fogline.state import parse_tile_key, state_hash
from fogline.viewer.app import STATIC, civ_turn, create_app

CIVS = sorted(spec.civ_id for spec in Config().civs)


@pytest.fixture(scope="module")
def client(town_run_dir):
    return TestClient(create_app(town_run_dir[0].parent), base_url="http://127.0.0.1")


def _frames(folder: Path) -> list[dict]:
    return [view.frame(snapshot.load(p)) for p in sorted(folder.glob("snap-*.json.gz"))]


def test_a_frame_copies_the_state_without_changing_it(town_run):
    state = town_run[0]
    before = state_hash(state)
    shown = view.frame(state)
    world = view.world(Config(), state)
    assert state_hash(state) == before
    assert [c["id"] for c in world["civs"]] == CIVS
    assert world["techs"] == 21  # the v1 tree (rules 14)
    assert {s["civ"] for s in shown["settlements"]} == set(CIVS)
    ids = [s["id"] for s in shown["settlements"]]
    decoded = {f"{x},{y}": ids[owner] for y, row in enumerate(shown["territory"])
               for x, owner in enumerate(row) if owner >= 0}
    assert decoded == state["territory"]
    assert len(shown["buildings"]) == sum(len(s["buildings"]) for s in state["settlements"].values())


def test_territory_indexes_follow_each_frames_own_settlement_list():
    state = worldgen.generate(Config(), 2)
    shown = view.frame(state)
    for y, row in enumerate(shown["territory"]):
        for x, owner in enumerate(row):
            if owner >= 0:
                assert state["territory"][f"{x},{y}"] == shown["settlements"][owner]["id"]
    assert all(parse_tile_key(s["tile"]) for s in shown["settlements"])


def test_the_viewer_shows_an_outpost_of_every_civ_grow_from_hamlet_to_town(town_run_dir):
    frames = _frames(town_run_dir[0])
    assert frames[0]["tick"] == 0 and frames[-1]["tick"] == town_run_dir[1]["tick"]
    for civ_id in CIVS:
        grown = [s["id"] for s in frames[-1]["settlements"]
                 if s["civ"] == civ_id and not s["capital"] and s["stage"] in ("town", "city")]
        assert grown, f"{civ_id} has no outpost town in the last frame"
        stages = [next(s["stage"] for s in f["settlements"] if s["id"] == grown[0]) for f in frames]
        assert stages[0] == "hamlet", (civ_id, stages[0])
        assert stages.index("town") > 0


def test_a_default_run_keeps_its_manifest_and_adds_supply_and_events(tmp_path):
    run.play(Config(), 1, 4, out=tmp_path / "plain")
    manifest = json.loads((tmp_path / "plain" / "manifest.json").read_text(encoding="ascii"))
    assert manifest == {"seed": 1, "ticks": 4, "bot": "builder", "config_hash": Config().config_hash(),
                        "events_enabled": True, "supply": 0, "llm": "bots", "llm_civs": [], "outputs": None,
                        "model": None, "slice_pair": []}


def test_the_api_lists_runs_and_serves_one_whole(client, town_run_dir):
    listed = client.get("/api/runs").json()
    assert [r["name"] for r in listed] == ["town-run"]
    assert listed[0]["supply"] == 50_000
    body = client.get("/api/runs/town-run").json()
    assert body["manifest"]["seed"] == 1
    assert body["world"]["size"] == town_run_dir[1]["map"]["size"]
    assert [f["tick"] for f in body["frames"]] == list(range(0, 201, Config().snapshot_every))


@pytest.mark.parametrize("name", ["nope", "..", "%2e%2e", "a%2fb", "town-run%00"])
def test_the_api_refuses_runs_it_did_not_list(client, name):
    assert client.get(f"/api/runs/{name}").status_code == 404


def test_folders_without_a_manifest_or_with_odd_names_are_not_runs(tmp_path):
    (tmp_path / "no-manifest").mkdir()
    (tmp_path / "bad name").mkdir()
    (tmp_path / "bad name" / "manifest.json").write_text("{}", encoding="ascii")
    client = TestClient(create_app(tmp_path), base_url="http://127.0.0.1")
    assert client.get("/api/runs").json() == []


def test_pages_carry_a_strict_content_policy_and_other_hosts_are_refused(client):
    page = client.get("/")
    assert page.status_code == 200
    assert "default-src 'self'" in page.headers["content-security-policy"]
    assert client.get("/", headers={"host": "evil.example"}).status_code == 400


STATIC_FILES = ("index.html", "viewer.js", "viewer.css")
SINKS = re.compile(r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|DOMParser|createContextualFragment"
                   r"|srcdoc|\beval\s*\(|new\s+Function|https?://")
INLINE_HANDLER = re.compile(r"<[^>]*\son[a-z]+\s*=", re.IGNORECASE)


@pytest.mark.parametrize("name", STATIC_FILES)
def test_the_page_never_writes_markup_from_data(name):
    # Phase 1 shows only engine-made names; this guards the sinks for when agent text arrives.
    text = (STATIC / name).read_text(encoding="utf-8")
    assert len(text) > 500, f"{name} is missing or empty"
    assert not SINKS.findall(text), SINKS.findall(text)
    assert not INLINE_HANDLER.search(text)


@pytest.fixture(scope="module")
def mock_client(tmp_path_factory):
    runs = tmp_path_factory.mktemp("inspector")
    run.play(Config(), 1, 20, out=runs / "mock-run", mode="mock", llm_civs=["verdance"])
    return TestClient(create_app(runs), base_url="http://127.0.0.1")


def test_the_inspector_returns_a_rulers_latest_turn_with_its_stored_output(mock_client):
    found = mock_client.get("/api/runs/mock-run/turns", params={"civ": "verdance", "tick": 12}).json()
    decide = found["decide"]
    assert decide["civ"] == "verdance" and decide["step"] == "decide" and decide["tick"] <= 12
    assert decide["output"]["status"] == "ok" and json.loads(decide["output"]["raw"])["end_turn"]
    assert decide["observation"]["tick"] == decide["tick"]
    assert found["reflect"]["tick"] == 8 and found["reflect"]["output"]["status"] == "ok"


def test_the_inspector_answers_plainly_when_there_is_nothing_to_show(mock_client, client):
    early = mock_client.get("/api/runs/mock-run/turns", params={"civ": "verdance", "tick": -1}).json()
    assert early["decide"] is None and early["reflect"] is None
    odd = mock_client.get("/api/runs/mock-run/turns", params={"civ": "../../etc", "tick": 20}).json()
    assert odd["decide"] is None  # a civ name is only compared with records, never used as a path
    scripted = client.get("/api/runs/town-run/turns", params={"civ": "verdance", "tick": 40}).json()
    assert scripted["decide"]["output"] is None  # a bots run keeps no outputs
    assert mock_client.get("/api/runs/no-such-run/turns", params={"civ": "verdance", "tick": 1}).status_code == 404


def test_the_inspector_shows_message_bodies_without_the_wrapper(tmp_path):
    seen = {"messages": [{"from": "Saltreach", "sent": 30, "hearsay": False,
                          "text": messages.wrap("abc123", "Salt for grain.")}]}
    record = {"civ": "verdance", "tick": 33, "step": "decide", "observation": seen}
    (tmp_path / "turns.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
    found = civ_turn(tmp_path, "verdance", 40)
    assert [m["body"] for m in found["messages"]] == ["Salt for grain."]
    assert found["decide"]["observation"] == seen  # the raw view the ruler saw is untouched
    assert civ_turn(tmp_path, "verdance", 10)["messages"] == []
