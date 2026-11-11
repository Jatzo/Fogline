# M5 sketch: turns, units, sight and contact

Status: sketch for approval. No code exists for this yet. Builds on 0e3ebb3 (research pool, build queue).

## In short

A turn is data. A decider (the scripted bot now, an LLM ruler in Phase 2) gets a `Brief` and returns a `Reply`, and never touches state. The engine finds which civs are due, builds every due civ's brief before any reply is applied, calls the deciders, then applies the replies in civ id order. Wakes are read off the existing `state["events"]` list through a per-civ cursor and one table from event kind to trigger, so no engine module has to call a `wake()` function. Units are a top-level table, each unit is a ledger owner with its own `pop`, and only `units.spawn` and `units.discharge` move people in and out. `sight.update` is the one writer of what each civ knows and whom it has met.

## Usage (written first; the types below follow from it)

The runner:

```python
state = worldgen.generate(config, seed=11)            # now also gives each civ one scout
deciders = {civ_id: bots.spiral_scout for civ_id in state["civs"]}
for _ in range(1000):
    records = engine.tick(config, state, ledger_log, deciders=deciders)
    transcript.extend(r.as_record() for r in records)  # kept outside the hashed state, keyed (tick, civ, step)
```

A scripted bot:

```python
def spiral_scout(brief: Brief) -> Reply:
    memory = dict(brief["memory"])
    leg = memory.get("leg", 0)
    if any(r["reason"] == "unreachable" for r in brief["rejections"]):
        leg += 1                                       # last waypoint was sea: skip it
    actions = []
    for unit in brief["units"]:
        if unit["kind"] == "scout" and unit["ready"] and not unit["target"]:
            actions.append({"kind": "move_unit", "unit": unit["id"], "to": spiral_point(leg)})  # "dx,dy"
            leg += 1
    memory["leg"] = leg
    return {"actions": actions,
            "end_turn": {"next_wake": {"ticks": 8, "triggers": ["unit_arrived", "unit_idle"]}},
            "memory": memory}
```

A test:

```python
def test_three_wholly_invalid_turns_skip_the_next(config):
    state = worldgen.generate(config, seed=3)
    seen = []
    def bad(brief):
        seen.append(brief)
        return {"actions": [{"kind": "build", "settlement": "nowhere", "building": "farm"}],
                "end_turn": {"next_wake": {"ticks": 1, "triggers": []}}}
    for _ in range(5):
        engine.tick(config, state, None, deciders={"ironhold": bad})
    assert [b["tick"] for b in seen] == [0, 1, 2, 4]   # tick 3 skipped
    assert seen[1]["rejections"] == [{"index": 0, "kind": "build", "reason": "not_own_settlement"}]
```

## Modules and who owns what

| Module | Single writer of | Public surface |
|---|---|---|
| `engine.py` (changed) | tick order | `tick(config, state, log, *, deciders=None) -> list[TurnRecord]` |
| `turns.py` (new) | `civ["turn"]` (wake time, subscribed triggers, event cursor, rejections, invalid streak, skip flag) | `Decider`, `Brief`, `Reply`, `TurnRecord`, `Trigger`, `step()`, `brief()` |
| `actions.py` (grows) | the action table and `Reason` codes | `ACTIONS`, `Reason`, `dispatch()`; handlers `allocate_workers`, `set_research`, `build`, `train_unit`, `move_unit`, `disband_unit` |
| `units.py` (new) | `state["units"]`, `civ["next_unit"]`, unit people in the ledger | `spawn`, `discharge`, `route`, `move_all`, `pay_upkeep` |
| `sight.py` (new) | `civ["known"]`, `civ["met"]`, `civ["in_view"]`, `civ["sites"]` | `visible()`, `update()` |
| `rules.py` (grows) | nothing (pure maths) | `reorder_shift()` |
| `bots.py` (new) | nothing in state | `spiral_scout`, `idle` |

Tracing a turn takes three files: `engine.tick` calls `turns.step`, which calls `actions.dispatch`, whose handler is in the same file and calls `units` for the ledger move.

Standing orders keep the owners they already have: allocation is `civ["allocation"]` (set only by `allocate_workers`), the build queue is `civ["build_queue"]` (set only by `build`), and the one new piece, reorder rules, is `civ["reorders"]` (set only by `end_turn`). `end_turn` does not carry an allocation or a queue, so there is one way to set each.

## State shape

```python
state["units"][unit_id] = {          # unit_id = f"{civ}-u{n}", n from civ["next_unit"], never reused
    "civ": str, "kind": str,         # "scout" | "levy" | "soldiers" (caravan arrives in Phase 3)
    "home": str,                     # settlement the people came from
    "tile": "x,y",
    "pop": int,                      # ledger stock, owner = unit id
    "ready_tick": int,               # trained once state["tick"] >= ready_tick
    "path": list[str],               # remaining tiles, worked out once when ordered; [] when idle
    "target": str,                   # "" when idle
    "idle_since": int,               # -1 while moving; raises unit_idle once
}

civ["turn"] = {"wake_at": int, "last_woke": int, "triggers": list[str], "cursor": int,
               "rejections": list[dict], "invalid_streak": int, "skip_next": bool, "below": list[str]}
civ["origin"]    = "x,y"             # founding capital tile; (0, 0) of every brief, fixed for the run
civ["known"]     = list[str]         # one "0"/"1" row string per map row, same layout as map["biome"]
civ["met"]       = dict[str, int]    # other civ -> tick of contact; the only gate on naming a civ
civ["in_view"]   = list[str]         # foreign unit ids in sight after the last step 4, sorted
civ["sites"]     = dict[str, dict]   # foreign settlement -> {"tile", "seen_tick"}; met civs only
civ["reorders"]  = list[dict]        # [{"stock", "below", "line", "workers"}], at most config.max_reorders
civ["next_unit"] = int
```

## Types and signatures

```python
# turns.py
class Trigger(StrEnum):            # the whole wake list (PLAN section 10); the one list
    MESSAGE_RECEIVED, OFFER_RECEIVED, OFFER_EXPIRING, TREATY_PROPOSED, ATTACK,   # no source until Phase 3 or 5
    UNIT_ARRIVED, UNIT_IDLE, BUILD_DONE, STOCK_BELOW_THRESHOLD, FOREIGN_UNIT_SIGHTED,
    CONTACT, TECH_UNLOCKED, HEARTBEAT
ALWAYS_ON = {ATTACK, CONTACT, TREATY_PROPOSED, OFFER_EXPIRING}
EVENT_TRIGGERS = {"built": BUILD_DONE, "tech": TECH_UNLOCKED, "contact": CONTACT, "sighted": FOREIGN_UNIT_SIGHTED,
                  "arrived": UNIT_ARRIVED, "idle": UNIT_IDLE, "below": STOCK_BELOW_THRESHOLD}

class Brief(TypedDict):    # whitelist copy; tiles "dx,dy" from civ["origin"]; foreign civs by name, met only
    tick, triggers, rejections, memory, stocks, stability, allocation, reorders, research,
    build_queue, settlements, units, known, in_view, foreign_sites, met
class Reply(TypedDict, total=False):
    actions: list[dict]          # each {"kind": <ACTIONS key>, ...}; tiles relative
    end_turn: {"next_wake": {"ticks": 1..8, "triggers": [...]}, "reorders": list | None}
    memory: dict                 # bots only; replaces civ["bot_memory"] after check_plain
Decider = Callable[[Brief], Reply]

@dataclass(frozen=True)
class TurnRecord: tick: int; civ: str; step: str; brief: Brief; reply: Reply | None; rejections: tuple

def step(config, state, deciders, log) -> list[TurnRecord]:
    # 1. due = civs (sorted) with a reason to wake; briefs built for all of them now, before any apply
    # 2. for each due civ: skipped -> clear skip_next, record "turn_skipped", leave the cursor alone;
    #    otherwise advance the cursor to len(state["events"]), set last_woke, call the decider
    #    (a plain loop in M5; Phase 2 makes this the concurrent part)
    # 3. apply replies in civ id order
def brief(config, state, civ_id) -> Brief           # the one builder: step, tests and the Phase 2 inspector
def _due(config, state, civ_id, now) -> list[dict]   # events after the cursor via EVENT_TRIGGERS, timer, heartbeat
def _apply(config, state, civ_id, reply, log) -> TurnRecord
    # first 12 actions -> actions.dispatch; the rest -> Reason.OVER_ACTION_CAP unread
    # at least one action and every one rejected -> invalid_streak += 1, else 0; at 3 -> skip_next
    # bad end_turn -> a rejection with index -1, and the civ is asked again next tick

# actions.py
class Reason(StrEnum)      # every code; M4 strings keep their values so M4 tests pass unchanged
@dataclass(frozen=True)
class ActionSpec: handler: Callable[..., Reason | None]; args: Mapping[str, str]   # "str" | "tile" | "tile?" | "alloc"
ACTIONS = {"allocate_workers", "set_research", "build", "train_unit", "move_unit", "disband_unit"}  # one row each
def dispatch(config, state, civ_id, raw) -> Reason | None
    # the boundary: shape check, relative tile -> absolute, then the handler; never raises on agent input

# units.py
def spawn(config, state, civ_id, kind, settlement_id, log, *, pay=True, at=None) -> str
    # TRAIN_COST (unless pay=False, for the starting scout), then TRAINED: settlement pop -n, unit pop +n
def discharge(state, unit_id, to_settlement, log) -> None    # DISBANDED both sides, then delete the unit
def route(config, state, unit_id, target) -> list[str] | None
    # A* over paths.enter_cost; ties broken by (cost, estimate, y, x) so every machine picks the same path
def move_all(config, state, now) -> None                      # step 4; sorted unit ids; leftover points lost
def pay_upkeep(config, state, civ_id, log) -> None            # step 6; unfed unit -> discharge home

# sight.py
def visible(config, state, civ_id) -> set[str]                # squares round units and settlements
def update(config, state, now) -> None
    # views for every civ first, then known bits, then contact for each sorted unmet pair (either sees -> both met,
    # "contact" event for both), then in_view ("sighted" for each newly seen unit) and sites
```

The tick:

```python
records = turns.step(config, state, deciders, log)   # 1
_production(...); _research(...)                     # 2 (reorder rules applied inside production)
units.move_all(...); sight.update(...)               # 4
_consumption(...)                                    # 6, now with units.pay_upkeep
_events(...)                                         # 7
```

## Where the rules are kept

- **People are conserved:** only `spawn` and `discharge` move people between a settlement and a unit, as a TRAINED or DISBANDED pair. Food and growth still use settlement population; unit people eat through UNIT_UPKEEP, so nobody eats twice. The conservation test also checks that every owner in the ledger totals that no longer exists (a disbanded unit) nets to 0.
- **No name before contact:** `civ["met"]` is written only by `sight.update` and read only by `turns.brief`. A test walks every brief of a 1,000-tick run and checks that no unmet civ's id or name appears.
- **Same path for bots and LLMs:** a decider only gets a `Brief` and only returns a `Reply`; `dispatch` is the only way in for agent actions.
- **Triggers during a call are queued:** the cursor moves when the decider is called, so anything recorded after that waits for the next wake. A skipped turn leaves the cursor where it was, so its triggers are not lost.
- **Fixed order:** briefs are built before any apply, replies applied in civ order, units moved in id order, contact pairs sorted. M5 draws no random numbers.

## Synthesis decision

Two candidates were sketched independently (one opus, one sonnet) and scored against a six-point rubric by a separate sonnet judge. Both the judge and I picked candidate 1 as the base. It builds every brief before applying any reply, which is the only order that survives Phase 2's concurrent calls. Every piece of state has one writer, and bots read a fog-honest brief instead of state.

Candidate 2 lost on ownership: `civ["allocation"]` had three writers (the action, the end-turn field and the reorder runner), triggers were raised from five modules, and its loop applied civ A's reply before building civ B's view.

Taken from candidate 2: an unfed unit disbands home through the same `discharge`, so people have one way out. Also the point that orders into land a civ has never seen leak ground truth; that is question 4 below.

Fixed from the judge's review of candidate 1: a skipped turn no longer advances the cursor (it lost triggers before), routes have a stated tie-break, and the test-only brief function is now the one public `brief()`.

Not taken: candidate 2's known-tiles map of first-seen ticks. Terrain never changes in v1, so a tick per tile is about 12 times the state for nothing a brief needs.

## Tradeoffs accepted

- I accept a small fog-honest `Brief` in M5, which looks like Phase 2 work, in exchange for bots going through the real fog and relative coordinates from the first 1,000-tick run.
- I accept event kinds becoming a wake contract, and `state["events"]` never being trimmed below the lowest cursor, in exchange for one mapping table instead of wake calls spread over five modules.
- I accept paths worked out once, on the true map, when a unit is ordered, in exchange for no path search per unit per tick. Roads in Phase 3 will need a re-route.
- I accept `deciders=None` as a mode of `tick`, so every M1 to M4 test runs unchanged.

## Alternatives considered

- **Push-model wakes** (`wake.fire()` at every source, a pending queue per civ). Clear at each call site, but the wake list spreads over five writers, a forgotten call is silent, and "fired during a call" needs its own rule.
- **Bots that read state** (`bot(config, state, civ_id)`). The smallest M5, but bots and LLMs would share only the output path. Fog and coordinate bugs would surface in Phase 2, and the RNG isolation test gets weaker.
- **A dataclass per action.** Better typing, but it lists every action twice and puts the wire format inside the engine.

## Open questions (my recommendation first)

1. **Sight shape:** a square of radius 2 (as footprints and claims already use), not a disc.
2. **Empty turn:** a turn with no actions resets the invalid streak.
3. **Unfed units:** a unit whose food upkeep can't be paid disbands home; its people survive.
4. **Orders into unknown land:** a move target must be within 2 tiles of known ground, and the path still runs on the true map. The `unreachable` code then reveals only a little.
5. **Skipped turn:** no call, and the civ is due again next tick with its triggers intact.
6. **Training:** a unit can't take a settlement's last person; at least 1 must stay.
7. **Score:** people serving in units count towards score population.
8. **The brief in M5** (question behind tradeoff 1): build it now (recommended), or let bots read state and leave fog for Phase 2.
9. **Re-sighting spam:** no cooldown on `foreign_unit_sighted`; the one-call-per-tick budget is the limit.

New numbers to approve: `max_wake_ticks` 8 (from rules 16), `max_reorders` 3, move-order margin 2, and the unit table from rules 6 as written.

## Next step

Add `state["units"]`, `units.spawn` and `units.discharge`, the starting scout in worldgen, and the conservation check for unit owners, before any turn or sight code. An ADR for reading wakes off the event log comes with the implementation.

## Where the build differs from this sketch

- A reorder rule is `{"stock", "below", "workers"}`: the line it fills is always the stock it watches, as rules 16 words it, so there is no separate `line`.
- `units.spawn` takes `ready_now` for the starting scout, and every action handler takes the ledger log, so units trained by a ruler appear in the per-tick log.
- Heartbeat and timer wakes show in a brief as `{"trigger": "heartbeat"}` and `{"trigger": "timer"}` but aren't in the `Trigger` list, because a ruler can't subscribe to them.
- A brief shows triggers without the event's own text, which can hold map tiles. Only contact and sightings carry a civ name, and stock thresholds carry the stock.
- Army upkeep is a running total in per mille, because rounding each unit's 1 × 1.25 down would hide the scale-up.
- Civs with no decider get no brief built, so the 1,000-tick economy runs stay fast.
