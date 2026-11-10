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

## Next session
Start Phase 1 in plan mode: write docs/rules.md and wait for approval.
