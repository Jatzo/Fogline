# 0007: Rulers call `claude -p` on the plan login, and every outcome is stored as text

## Decision
A ruler's turn goes through one adapter interface: `call((tick, civ, step), observation) -> Outcome(status, raw)`.
- **Live calls** (`llm.LiveAdapter`) run `claude -p --model claude-haiku-5-5 --output-format json` as a subprocess, on the operator's Claude plan login. The system prompt is the ruler prompt and the observation is the user message. It runs in an empty temporary folder with `--tools ""`, `--strict-mcp-config` and `--no-session-persistence`.
- **Storage:** every call is kept as one row in `outputs.jsonl`: `{tick, civ, step, status, raw, obs_hash}`. `status` is `ok`, `timeout` or `error`, and `raw` is the reply text exactly as it came back.
- **Replay** (`llm.ReplayAdapter`) answers from those rows. It never calls or times anything, and it fails loudly on a missing row, or when the observation's hash differs from the one the row answered.
- **Mocks:** tests and the mock runs use `llm.MockAdapter`, which wraps the scripted bots and emits JSON text, so the parse path always runs.

## Why
- **The plan login:** PLAN section 1 decided calls go through the plan, not a paid API key. `claude -p` is the supported way to do that from a script. The SDK would need an API key, and `--bare` mode also needs one, so neither fits.
- **Storing status as well as text:** a timeout is decided by the wall clock. If replay re-timed calls, a slow machine could turn a stored reply into an empty turn and the run would fork. Replaying the stored status makes a timeout part of the record.
- **Storing raw text, not parsed replies:** the parser and validator can change, and a replay should show what the model actually said. Replaying the text through today's `schema.validate_reply` also checks that old outputs still mean what they did.
- **The observation hash:** this is what makes replay a check rather than a playback. In the isolation test, one civ's outputs are swapped for a different ruler while the others replay. Any change that leaked into another civ's observation would stop the replay at that call.

## What the smoke call showed (2026-11-11, one call, seed 1 Verdance at tick 0)
- The call took 12.0 seconds, the output envelope was well-formed, and `modelUsage` reported `claude-haiku-5-5`. stderr carried an `unrecognized_model` warning that didn't stop the call.
- The reported cost was $0.072. Of 1,222 output tokens, 1,024 were thinking: extended thinking is on by default. At 650 to 900 ruler calls per run (PLAN section 10), that is roughly $47 to $65 of notional cost per run before diplomacy, on the plan's usage limits rather than a bill.
- The reply was well-formed JSON, but it put `reorders` at the top level instead of inside `end_turn`, so `validate_reply` refused it as `malformed`. The prompt will need to be explicit about the shape (M13).
- The call reported 5,985 input tokens for about 6,400 characters of prompt and observation, which should be roughly 1,600 to 2,000 tokens. **Something else reaches the model. I have not yet found out what.** It may be Claude Code's own framing, or the operator's user-level instructions. The output envelope has `system_prompt_detail` and `input_attachments_detail` fields that should say. Until that is settled, a live ruler's context is not proven to be only the prompt and its observation.

## Not chosen
- **The Anthropic SDK with an API key.** It would be faster, give exact token counts and allow thinking to be switched off, but it needs a paid key, against the project decision.
- **Storing parsed replies.** They would be smaller and simpler to replay, but they would hide what the model really said, and couldn't be re-validated.
- **Replaying with live timeouts.** Truer to a re-run, but not reproducible.

## What I would not trust
- **Clean context:** see the input-token gap above. It has to be resolved before any live ruler plays a civ that could meet another (Phase 3).
- **Cost per call:** one call is not a measurement. Phase 3 records cost per 100 ticks with and without contact.
- **The `claude -p` interface:** a CLI update could change the flags, the output envelope or the default model handling. The live adapter treats anything unexpected as an `error` outcome rather than guessing.
