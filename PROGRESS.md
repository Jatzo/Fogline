# Progress

Update this at the end of every Claude Code session.

## Phases
- [ ] 1. Rules spec, then engine (with tile viewer showing settlements grow)
- [ ] 2. Agent interface
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
- Low: a stage drops one band per 4 ticks; a reply nested about 1,000 deep raises `RecursionError` (matters in Phase 2).

Rulings and tests after the review (183 tests):
- The 4-tick growth window counts unit food upkeep, due whether paid or not (rules 4.1 and 21). Golden hash re-pinned: every civ starts with a scout.
- Luxury +5 holds for 4 ticks and every settlement uses luxury; a civ's brief lists nodes on all its own land (rules 21, no code change).
- Behaviour tests for tool shortage, cold deaths, luxury use, drought and comet durations and the secession idle window; each fails when its rule is broken.

## Phase 2 plan (approved 2026-11-11)
Milestones: M8 observation and sea border, M9 schemas and the frontier rule, M10 LLM adapter and stored outputs, M11 scheduler and runner, M12 memory, M13 prompts and the 200-tick mock run, M14 civ inspector. Decisions: live calls through a `claude -p` subprocess on the plan login; schemas from `ACTIONS` with no new dependency; allocation and the build queue stay persistent actions; the inspector is a viewer panel; a sea border; unseen move targets are always accepted (M9).

## Phase 2 milestones
- [x] M8 sea border (map 72, land 64 inside 4 tiles of sea; tree window re-measured at 329 to 438, now 300 to 450), `observation.observe()` with a whitelist and a 12,000-character cap, bots on the same observation plus scratch memory, fog tests over 10 seeds with a metamorphic check (ADR 0006; 188 tests)

## Next session
M9: typed schemas, reply validation and the frontier rule.
