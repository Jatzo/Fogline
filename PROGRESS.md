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
- [ ] M6 part 1 committed: snapshot.py, run.py (headless runner and run folder), builder bot, brief gains held techs and own nodes, no-ruin rule for fields and camps, tuned starting stocks and winter fuel 2; tests for the smoke run, determinism across processes, golden hash (seed 1, tick 200), RNG isolation, fresh-process resume, snapshot round trip, run-out schedule and decline (146 tests). Dunerunners timber raised to 800 (approved 2026-11-11). Still to do: tree pace, outpost to town.
- [ ] M7 viewer

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
- Measured with scratch probes: supplied at 2,000 (food, timber, stone, metal), every civ finishes the tree at 311 to 384 on seeds 1 to 5; supplied at 50,000, every civ has an outpost town by 132 to 175.

## Next session
M6 part 2: options for tree pace and outpost growth, then their tests. Then M7, the viewer.
