# Progress

Update this at the end of every Claude Code session.

## Phases
- [x] 1. Rules spec, then engine (with tile viewer showing settlements grow)
- [x] 2. Agent interface
- [ ] 3. Contact (3a messaging, trade, caravans, diffusion; 3b two LLM civs, close together)
- [ ] 4. Five civs, natural contact
- [ ] 5. Conflict and the record (5a treaties/raids, 5b Chronicler/replay)
- [ ] 6. Viewer v1 (city view, time scrubber, all panels)
- [ ] 7. Experiments, research and case study

## Decisions made
- Same model (Haiku 5.5) for all rulers, different cultures plus engine-enforced modifiers
- Calls go through the Claude plan login, not a paid API key
- Whole repo is public except secrets, voice.md, private/ and runs/
- Experiments: 5 arms each, 5 seeds per arm
- Temperament dial sets starting reputation and prompt self-description only; no engine bonus of its own
- No world leader: engine + read-only Chronicler; operator is "Providence"
- Normal language from first contact
- Runs on the operator's Claude plan; campaign-style resumable play
- Research and case study are written by the operator; Claude supplies evidence packs and draft tables
- v1 tech tree cut to 21 nodes over three eras; gunpowder, banking, steam, railways, telegraph and ships are v2
- docs/rules.md approved 2026-11-10, after one opus review round; PLAN.md patched for its 14 departures
- Outposts 7 to 9 tiles from the capital; default allocation, quirk effects and rule readings in rules.md section 21 (approved 2026-11-10)
- M4 readings (approved 2026-11-10): one research pool (ADR 0002); build queue of 5, one build per settlement, paid at start; building at the end of step 7; repair 1 tick; stage drops keep land; printing x1.5 from the printing house; coast is fishing ground; hints and catch-up wait for Phase 2 and 3
- M5 design (approved 2026-11-11): docs/design/m5-sketch.md, with its 9 open questions settled as recommended; readings in rules.md section 21

## Open numbers (tuned by Phase 1 and Phase 4 tests)
- Run-out schedule (rules 4.7): starting stocks and small-node sizes
- Tech pace (rules 14): era costs
- Contact timing (rules 6): start spacing, outpost placement, scout move; map may grow to 80 x 80

## Phase 1 milestones
- [x] M1 foundations: config, intmath, rng, state, ledger, CI, ADR 0001
- [x] M2 worldgen: spaced capitals, home regions, nodes, outposts, town traits
- [x] M3 economy tick: production with worker allocation, consumption, upkeep, growth, starvation, stability, unrest, secession, Providence and quirk events (75 tests)
- [x] M4 tech tree, research pool, build queue, placement, contestable claims, growth stages, fishing (104 tests)
- [x] M5 units, sight and contact, the turn path (briefs, replies, one action table with reason codes), wakes off the event log (ADR 0003), reorder rules, spiral scout bot (128 tests)
- [x] M6 runner, snapshots, builder bot and tuning: run-out schedule and decline in isolation, tree pace and towns in a supplied world (ADR 0004), first debug-log entry (160 tests)
- [x] M7 read-only viewer: `fogline/view.py` frames, a local FastAPI app, a painted map with a time-lapse over snapshots, `--supply` on the runner (ADR 0005; 175 tests)

## Found in M3
- With no bot building anything, every civ dies out by about tick 100 on seed 1: stone runs out, upkeep goes unpaid, farms become ruins, then everyone starves. Rules 4.7 expects a decline to what the land supports, not extinction. This gets checked again with scripted bots in M6 before any number changes.
- In M5, a spiral scout run on seed 1 maps 333 to 595 tiles per civ in 200 ticks, with no contact. Scouts starve once a civ with no economy bot runs out of food. Bots that hit sea or unseen land three turns running get skipped, as the rules intend.
- Fixed in M4: coast in a settlement's land now counts as a fishing ground.
- With a crude builder that queues buildings nonstop, timber goes on buildings, research stalls (3 techs in 200 ticks on seed 1) and civs still die out. Real bots and tuning come in M6.

## M6 tuning measurements (events off, builder bot, 2026-11-11)
- As the rules stand, seeds 1 to 5: critical stocks run out at ticks 11 to 55 (target 60 to 80); every civ but Saltreach is extinct by tick 100; no civ finishes the tree or grows an outpost to town. Cause: when timber or stone hits 0, every building goes into arrears at once and 8 ticks later all of them are ruins, farms and lumber camps included, so nothing can recover.
- Experiment (not committed): if farms, pastures, lumber camps and mines never ruin (half output while in arrears), every civ survives to tick 400 at 15 to 61 people. Run-out, tree pace and towns are still well short.

- Approved and in the working tree: farms, pastures, lumber camps and mines never ruin (rules 21); food-short civs research Crop rotation first. Civs now decline instead of dying out.
- Experiment on seeds 1 to 3 (not yet approved): stocks Ironhold food 2000, Dunerunners food 2000 and timber 300, Saltreach timber 400, Frostmark stone 220, Verdance metal 110, winter fuel 2 per 10, and two bot rules (mine a metal node when metal falls; no new housing while timber falls). Run-out: Ironhold food 54 to 79, Dunerunners food 54 to 84 and timber 23 to 58, Saltreach timber 39 to 53, Frostmark stone 63, Verdance metal 83 to 87. Every civ's food output is at least 33% below its peak by tick 100. Tool wear at 1 per 40 workers changed nothing.
- Still failing: no civ gets past 13 of 21 techs by tick 400, and no outpost passes 10 people by tick 400.

## M6 part 2 decisions (approved 2026-11-11)
- Cause found: in isolation every civ's timber nets to about zero by tick 40, so the library and workshop become ruins and research stops at tick 100. Tree costs were not the problem.
- Tree pace and towns are measured in a supplied world (stand-in for trade, ADR 0004); the isolation tests stay unsupplied.
- Era points doubled (160, 480, 1,200); growth may also run on a store of 40 ticks of eating; starting stocks Ironhold food 1,500, Dunerunners timber 650, Saltreach timber 600.
- Builder bot: farms go where people lack work (first debug-log entry), housing pauses only while timber falls and is under 100.
- Measured with scratch probes: supplied at 2,000 (food, timber, stone, metal), every civ finishes the tree at 311 to 384 on seeds 1 to 5; supplied at 50,000, every civ has an outpost town by 132 to 175. The tests on seed 1 give 312 to 383 and 131 to 174.

## M7 notes (2026-11-11)
- To watch a run: `python -m fogline.run --seed 1 --ticks 400 --supply 50000 --no-events --out runs/demo-seed1`, then `python -m fogline.viewer --runs runs` and open http://127.0.0.1:8000.
- On that run every civ's outposts start as hamlets and reach town; each civ ends near 1,225 people with 2 villages and 2 towns.
- The map is painted rather than a tile grid (the operator's call): warped biome edges, trees, peaks, culture roof styles, lanes that branch, frontiers smoothed by marching squares.
- One request loads the whole run: 4.8 MB and 0.9 s for 101 snapshots; the terrain paints once in about 1.3 s, then each frame draws in about 6 ms.

## Phase 1 review (2026-11-11)
Two reviews, one of the engine and economy and one of worldgen, turns, units, sight and the runner. Fixed (176 tests):
- A foreign unit id now answers `unknown_unit`, like a made-up one, so a guess can't reveal a civ before contact.
- Contestable nodes are placed after founding and never start in anyone's land (21 of 100 seeds did; debug log). Seed 1 golden hash re-pinned.
- The runner refuses an `--out` folder that isn't empty.
- Rules 21: a building owes one upkeep bill at most (approved, no code change).

Deferred:
- Snapshot load doesn't check the config hash. No resume path outside the tests yet; lands with campaign resume.
- Low: a stage drops one band per 4 ticks. (The deep-reply `RecursionError` is fixed in M9.)

Rulings and tests after the review (183 tests):
- The 4-tick growth window counts unit food upkeep, due whether paid or not (rules 4.1 and 21). Golden hash re-pinned: every civ starts with a scout.
- Luxury +5 holds for 4 ticks and every settlement uses luxury; a civ's brief lists nodes on all its own land (rules 21, no code change).
- Behaviour tests for tool shortage, cold deaths, luxury use, drought and comet durations and the secession idle window; each fails when its rule is broken.

## Phase 2 plan (approved 2026-11-11)
Milestones: M8 observation and sea border, M9 schemas and the frontier rule, M10 LLM adapter and stored outputs, M11 scheduler and runner, M12 memory, M13 prompts and the 200-tick mock run, M14 civ inspector. Decisions: live calls through a `claude -p` subprocess on the plan login; schemas from `ACTIONS` with no new dependency; allocation and the build queue stay persistent actions; the inspector is a viewer panel; a sea border; unseen move targets are always accepted (M9).

## Phase 2 milestones
- [x] M8 sea border (map 72, land 64 inside 4 tiles of sea; tree window re-measured at 329 to 438, now 300 to 450), `observation.observe()` with a whitelist and a 12,000-character cap, bots on the same observation plus scratch memory, fog tests over 10 seeds with a metamorphic check (ADR 0006; 188 tests)

- [x] M9 typed arguments in `actions.action_table()`, `schema.validate_reply()` (20,000-character cap, JSON, depth 8, top-level keys) and `schema.json_schema()` exported from the table; move orders route over the civ's seen map, so unseen sea no longer answers "unreachable"; a 2,000-deep reply is refused, not crashed on. `set_note` moves to M12 with the memory API it writes to (214 tests)

- [x] M10 `fogline/llm.py`: mock, live (`claude -p` on the plan login), recorder and replay adapters; outputs stored as status plus raw text plus observation hash; `turns.Refused` for text that never became a reply; replay of a recorded mock run gives the same hash; swapping one civ's ruler leaves the others' observations byte-identical. One live smoke call: 12 s, $0.072 reported, 1,024 thinking tokens, reply refused as malformed (`reorders` at the top level). Found by a second call: `claude -p` adds about 2,850 tokens of the operator's user-level context (instructions and hook output) to every call, even with `--system-prompt`. Fixed with `--safe-mode`: a tiny call fell from 2,864 to 1,041 input tokens with no user context built, and default thinking went too ($0.0084 a tiny call). About 1,000 tokens of Claude Code's own framing remain (ADR 0007). A depth check before parsing fixed a Windows and Linux disagreement (debug log). 222 tests.

- [x] M11 `fogline/scheduler.py` calls woken rulers together (cap 5) and applies replies in civ order; the recorder writes under a lock (parallel calls had interleaved lines); `run --llm bots|mock|replay|live --llm-civs --outputs --prompt`, with mode, civs, outputs and model in the manifest and call counts by status in the summary. A 200-tick mock run on seed 1: 558 calls in 4.6 s, replayed to the same hash in 3.1 s. Plan correction: a tick is a season, so the per-season budget is the existing one decide call per civ per tick; deferral comes with reflection in M12. 230 tests.

- [x] M12 `fogline/memory.py`: journal (16 × 200 characters) and strategy notes (800), written only through `memory.write` with a source tag and provenance; `set_note` action (own inference only); the observation shows journal and strategy, and trims old journal entries after the distant map and before events; LLM rulers reflect every 8 ticks after decide as step `reflect` (the mock writes a plain summary), scripted bots don't. No budget deferral: one decide plus one reflection per civ per tick can't go over. 242 tests.

- [x] M13 `prompts/ruler.md` and `prompts/cultures/verdance.md` (approved by the operator 2026-11-11), `fogline/prompts.py` builds one system prompt per civ, `run --llm live` uses them (no `--prompt` flag), the mock ruler (builder plus `set_note`, a seeded bad order about one turn in ten), the prompt-leak check and the Phase 2 check over a recorded 200-tick game. The leak check found two leaks, both fixed: the schema listed wake triggers that only make sense with others (`contact`, `foreign_unit_sighted` and so on), and the observation carried `met`, `in_view` and `foreign_sites` from tick 0. Phase 2 run: 678 calls (120 reflections) on seed 1, replayed to the same hash. 247 tests.

- [x] M14 the civ inspector: `/api/runs/{name}/turns?civ=&tick=` (the run found through the listing; civ and tick only compared with records) returns a civ's latest turn and reflection at or before a tick, with the stored output; the viewer's "Ruler's turn" panel follows the time-lapse when paused and shows why the civ woke, the outcome, orders, rejections, journal, strategy, the raw reply and the full observation, all through textContent. Checked in the browser on a 200-tick mock run. 249 tests.

## Phase 2 review (2026-11-11)
Two reviews: fog and prompts; adapter, replay, scheduler and memory. No determinism or replay break found. Fixed:
- A ruler's rejected `kind` is cut to 40 characters; a 19,000-character one had made the next observation 20,921 characters against a 12,000 cap. Rejections are the last thing trimmed.
- The sea border is 6 tiles (map 76): a stone fortress sees 4, and a move order reaches 2 past known ground. A test ties the border to every sight radius.
- A live run stops after 3 ticks in a row where every call errored, or 5 of timeouts.
- Each live output keeps whitelisted token counts and cost; the summary totals them per civ.
- Verdance's culture lost "strike first", "by force" and "neighbour"; the leak check now looks for those words, enemy and invade.

Deferred: replay doesn't check that every stored row was used or that the manifest matches; fenced JSON from Haiku is refused (kept strict; watch the first live run); the event token mapper misses an id with punctuation attached; a trigger naming an unmet civ keeps its name with the detail blanked (matters once Phase 3 adds pre-contact triggers); outputs.jsonl lines are in finish order.

## Phase 3 plan (approved 2026-11-11)
Milestones: M15 contact surface (reputation, met civs as words, widened triggers after contact, unmet names refused like made-up ones, tech catch-up and hints); M16 messages, couriers, hardening (NFKC, strip control and markup and role markers until stable, a fresh delimiter per message) and foreign claims (80-character quotes; no laundering into own notes); M17 trade, caravans, escrow, fee, valuation, blueprints, reputation from acts, tracks, dossiers, scripted trader (ADR 0008); M18 slice setup (Saltreach culture, slice placement, cost meter, no-contact baseline, inspector); M19 the live slice after an approved cost estimate.

Decisions: caravan 20 timber and 10 food, 2 people, 1 food upkeep, move 4, 1 tick to train, carries 100 (200 with Carts); slice pair Verdance and Saltreach; dossiers are engine facts plus the ruler's notes; a message wakes the receiver next tick (no same-tick replies). Readings: the fee is halved on the receiver's view of 30 or more; fees are per good, rounded down; a bundle is valued at last pair prices against food, else base values; a reserved caravan walks to its nearest settlement first and can't be moved while reserved; dossiers don't score claims against truth or list grievances in v1.

Tick order: step 1 queues couriers (delivery tick fixed at dispatch), escrows offers and acceptances; production, research; a new trade step expires offers and forms legs; movement advances legs and delivers due couriers; leg delivery (fee, blueprints, reputation, tracks) before sight; reputation drifts in events every 4 ticks. New ledger rules: escrow, escrow return, loaded, trade delivery, market fee; blueprints are minted and destroyed as logged events, not ledger rules (ADR 0008); escrow owner `offer-<id>-give` and `offer-<id>-get`, transit owner the leg unit.

## Phase 3 milestones
- [x] M15 reputation per ordered pair with drift; met civs shown as a word; schema and system prompt widen after contact (live prompts built per call from the observation); `actions.met_civ` answers an unmet civ like a made-up name; triggers naming an unmet civ dropped; ids matched through punctuation; tech catch-up 25% for a tech a met civ holds; every offered tech has a hint. The cap of 3 offered techs was dropped (operator's call): it broke 8 tuned tests by narrowing the builder's choices. 272 tests.

- [x] M16 `fogline/messages.py`: hardening, couriers with the delivery tick fixed at dispatch, a fresh 12-hex delimiter per message from a new messages RNG stream, hearsay; `send_message`; inbox in the observation (after contact only) with `message_received`; contact-only actions and fields hidden from the schema and answered like made-up ones before contact; foreign claims and the anti-laundering check in `memory.write`; the inspector shows messages and hearsay. Known limits: role markers are stripped at the start of a line only, and lookalike letters outside NFKC (Cyrillic) aren't normalised; the per-message wrapper is the defence there. Corpus of 13 hostile texts; 30 ticks with and without a message leave the world identical apart from the inbox. 297 tests.

- [x] M17 `fogline/trade.py`: offers escrow the giver's goods and reserve caravans; acceptance escrows the receiver's; caravan legs travel the real map and deliver less the fee; expiry and refusal return the escrow; blueprints minted and unlocked or destroyed; reputation from deliveries and aid; prices from one-good-for-food trades; tracks; offers and dossiers in the observation after contact; the scripted trader (`--bot trader`). Conservation now covers escrow and cargo. 3a done-when: scripted traders complete a trade end to end, and a blueprint unlocks writing for a buyer who can use it and is destroyed for one who can't (ADR 0008). 308 tests.

- [x] M18 the Saltreach culture (approved 2026-11-11); `--slice` placement (meet at tick 0 on seeds 1 to 5); the cost meter split at first contact with per-100-tick figures and call counts; the mock ruler now trades and greets each people it meets; the inspector shows offers and known peoples. Mock slice, seed 1, 150 ticks: 2 messages, 39 offers (4 done, 34 expired), 8 deliveries, 23 tracks; replays to the same hash. Mock baseline (no slice): Verdance meets no one in 150 ticks (104 calls), Saltreach meets a scripted neighbour at tick 78. Slice placement moves Verdance's metal run-out on seed 1 from 80 to 91 (accepted). 317 tests.

- [x] M19 the live slice. A tiny call before the runs reported 1,047 input tokens, so safe mode still holds. Live runs on the plan login, seed 1, 150 ticks, Verdance and Saltreach as live rulers, scripted trader neighbours: live-slice-s1 (266 calls, none failed, $46.28 notional) and live-baseline-s1 (237 calls, none failed, $35.55); both replay exactly to their tick-148 snapshots. Per LLM civ per 100 ticks: 50.0 to 52.9 calls and $3.54 to $3.93 before contact (15 and 18 calls, contact at ticks 29 and 33), 80.2 to 92.5 calls and $10.89 to $17.11 after (split corrected in the Phase 3 review). A call costs about $0.15 to $0.17, against $0.07 for the smoke call, because thinking is still on, so I corrected ADR 0007. Call budget kept as it was, with no cost guard (approved 2026-11-13; rules section 21). Numbers in `research/m19-cost-draft.md`. The inspector now shows each message's body without the wrapper. 320 tests.

## Phase 3 review (2026-11-13)
Two reviews: contact, fog and messages; trade, escrow and the cost meter. No determinism break found; every iteration that matters is sorted. Fixed (322 tests):
- Hearsay now replaces every word that starts with an unmet civ's name or id; "The Frostmarkers" used to pass through to a civ that hadn't met them.
- Before contact a caravan order is refused as an unknown unit before the settlement is checked; a probe with a bad settlement could tell a hidden unit from a made-up one.
- The anti-laundering check searches the lowered texts by their own lengths; a note padded with "İ" (2 characters lowered) hid a copied message from it.
- The conservation test now checks that escrow, escrow return, loading and trade delivery each net to zero across owners; before, a transfer that dropped the receiving side would have passed.
- A blueprint in an offer that expires or is refused is logged as destroyed, as ADR 0008 says.
- Each civ records the first turn that could see contact (the turn after the tick it was found in, turn 0 at setup), and the cost meter splits on it; it had counted a turn in the contact tick as after contact. The M19 figures are recomputed from the stored outputs. The new field changes the golden hash; with the field removed the state hashes to the old value.

Deferred, operator's call: offer ids are global, so a civ that has met only some others can see gaps from trades it isn't part of (matters once 3 or more civs trade); the market fee is rounded per caravan, so splitting cargo or small lots pays less; one trade can set any price, which then values aid and fair-trade reputation; a journal entry shows `source` and `about` before contact. Pressure mechanics are left for Phase 4 (operator's call). Not reviewed: replay code in `run.py`, `bots.py`, `mock_ruler.py`, `--slice` placement, `paths.py`, `turns.py` beyond trigger raising. No Phase 3 entry in the debug log: no non-trivial bug came up during the build.

## Phase 4 readiness (2026-11-13)
Built so the Phase 4 live run can start once the operator approves it. Nothing live has been run.
- Cultures for Ironhold, Frostmark and Dunerunners in `prompts/cultures/`, written to the temperament dials and culture modifiers; they pass the leak checks (one caught "met" in Frostmark's first draft). **Pending approval.**
- Contact timing: spiral scouts met first at a median of tick 96 (seeds 1 to 10). A capital ring of 19 fixed it (47) but broke 10 tuned tests and errored 11, so scouts now move 8 (10 with Pathfinding): median 55.5 on seeds 1 to 10, 49.5 on held-out seeds 11 to 20 (ADR 0009). **Pending approval:** it puts aside the spacing-first order in rules section 6. The golden hash changed for this alone.
- `fogline/phase4.py` checks a finished run: last tick reached, 3 building types per civ, mean pairwise action-mix divergence against 0.05, first contact reported. A run now saves its last tick as a snapshot.
- `--resume <folder>` carries on a stopped mock or live run by replaying its stored outputs from tick 0 against the last saved snapshot, then calling afresh; the stopped session is archived in the folder and restored if the replay fails (ADR 0010). Tested on the mock only.
- Mock run, seed 1, 400 ticks, five mock rulers: completes; 1,334 calls; first contact 46 to 77; divergence 0.0558; building types 3, 4, 2, 4, 4, so the mock's Ironhold (farms and mines only) fails the building check.
- On the M19 live slice the check reads divergence 0.012 between the two live rulers, and 2 building types each in 150 ticks.
- Cost estimate for one live run, seed 1, 400 ticks, five live rulers: 1,519 to 1,738 calls, $197 to $305 notional (`research/phase4-cost-estimate-draft.md`). **Pending approval.**
- A test made one real live call once Ironhold had a culture (Ironhold, 1 tick, $0.075 notional). Fixed, with a guard in `tests/conftest.py` that fails any test starting `claude` (docs/debug-log.md).
- A review of these changes found that a failed resume could leave a replayed snapshot to check against, that dropped calls were lost from the files and the cost, that one kindless refusal wiped a turn from the action count, and four culture lines that hinted at outsiders. All fixed.
- 337 tests.

## Viewer in 3D (2026-11-13)
The operator picked the tabletop diorama from three directions. The map is now a carved block on a walnut table in three.js 0.170.0, vendored and pinned (ADR 0011): low-poly relief, strata on the cut sides, the sea as clear water, instanced trees and rocks, procedural houses, keeps, fields and mines in each culture's colours, territory and borders, town name cards, orbit, slide and zoom. Everything you read moved to a strip along the bottom. The flat map stays as a fallback (no WebGL, or `?flat`). The ruler's-turn panel now waits until stepping pauses and says which tick it is reading, which was the cause of the stale "none" seen in M19. The viewer sends `Cache-Control: no-cache` and serves `.js` as JavaScript. A step rebuilds in 11 ms (median); render time not measured (the pane was hidden). Seasonal light was dropped: every snapshot falls in the same season.

Following a run as it plays: snapshots are now written to a `.part` file and renamed into place, so a reader never sees half of one; the viewer reads a turn log that ends in half a line; `/api/runs/<name>/frames?after=<tick>` returns only newer frames. A run that hasn't reached its last tick opens on its newest frame with Follow on; every 10 seconds the viewer fetches new frames, moves on if you're on the newest and stays put if you've looked back, and shows the latest turn (logged every tick, while frames come every 4). Checked in the browser against a folder growing by a snapshot every 3 seconds. The first-drag jump from the review is fixed. 343 tests.

## Next session
Phase 4 live run, once the operator approves the three cultures, scout move 8 and the cost. Before it, check a tiny call's input tokens (ADR 0007). Command: `python -m fogline.run --seed 1 --ticks 400 --llm live --out runs/p4-live-s1`; if it stops, `python -m fogline.run --resume runs/p4-live-s1`; then `python -m fogline.phase4 runs/p4-live-s1`.
