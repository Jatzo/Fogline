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

## Open numbers (tuned by Phase 1 and Phase 4 tests)
- Run-out schedule (rules 4.7): starting stocks and small-node sizes
- Tech pace (rules 14): era costs
- Contact timing (rules 6): start spacing, outpost placement, scout move; map may grow to 80 x 80

## Next session
Phase 1 engine, in this order: config, rng, state, worldgen, rules, tick loop, actions and validation, snapshot, headless runner, scripted bots, then the read-only viewer. Write tests alongside each module (testing-strategy skill). Add the CI workflow first, and an ADR for the integer and civ-wide stockpile choices.
