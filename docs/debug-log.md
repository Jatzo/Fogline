# Debug log

Non-trivial bugs: what broke, how I found it, the fix, and the test that would catch it again.

## 2026-11-11: the builder bot starved its own growth by farming the wrong town

**What broke.** In supplied test runs, where stocks never ran out, outposts still froze at about 21 people
from tick 90 to the end of a 400-tick run. No outpost reached town on any seed.

**How I found it.** I traced each settlement of seed 1 Verdance every 30 ticks: population, buildings and
the civ's 4-tick food window. At tick 90 the chosen town had 32 farms and 21 people. The capital had 159
people and 4 farms. Most of the town's farms had nobody to work them, the capital's farm workers couldn't
feed it, and the civ-wide food check failed from then on, so no settlement grew again.

The cause was one line in `fogline/bots.py`. When food fell, the bot tried the town first, then the
capital, then the other outposts, and stopped at the first one free to build. The town was almost always
free, so it got every farm.

**The fix.** A new farm now goes to the settlement with the most people beyond its farm, mine and lumber
camp slots. I counted only field work because that is the version I measured: counting workshop and
library slots as well, and trying the next settlement when one is blocked, moved Ironhold's food run-out
on seed 1 from tick 79 to 48.

**Regression test.** `test_the_builder_puts_a_new_farm_where_people_lack_work_not_in_its_town` in
`tests/test_turns.py` rebuilds the tick-90 Verdance case and checks that the farm goes to the capital. On
the old bot it fails with `['verdance-3'] == ['verdance-0']`.

## 2026-11-11: outposts claimed nodes that were meant to belong to nobody

**What broke.** Rules section 2 places 3 to 5 contestable nodes in the gaps between home regions, for two
civs to compete over. On 21 of 100 seeds at least one of them started inside a civ's own land, so the
builder bot could put a mine or camp on it straight away.

**How I found it.** The end-of-phase review flagged the order in `worldgen.generate`. Contestable nodes
were placed first and only kept out of the 10-tile home radius. Outposts came after, sit up to 9 tiles
out and claim 4 tiles round them. A script over seeds 1 to 100 that checked every `contest-*` tile
against the territory map found the 21.

**The fix.** Contestable nodes are now placed after every civ is founded, on tiles nobody has claimed.
If fewer than 3 fit, worldgen rerolls the attempt, as it already does for other placement rules. Every
world shifts slightly, so the seed 1 golden hash moved. The run-out, decline and tree-pace tests passed
unchanged.

**Regression test.** `test_contestable_nodes_exist_and_belong_to_nobody` in `tests/test_worldgen.py` now
also checks that no contestable node sits in anyone's land, on seeds 1 to 20. On the old order it fails
on seed 7.

## 2026-11-11: a deep reply got a different answer on Linux than on Windows

**What broke.** CI failed on the M9 commit, while the same 214 tests passed on my machine. The one failure was a reply of 3,000 nested brackets. `schema.validate_reply` is meant to refuse it, and the test expected the reason detail `not_json`. On the CI runner it came back as `too_deep`.

**How I found it.** The CI log named the case. The order in `validate_reply` was: parse with `json.loads`, then measure depth. On Windows the parser hit Python's recursion limit and raised `RecursionError`, which I caught as "not JSON". On the Linux runner the parser got through 3,000 levels, and the depth check then refused it. The test had pinned whatever my machine did. A replayable engine can't have a ruler's reply judged differently by platform.

**The fix.** `schema.text_depth` measures bracket depth on the raw text before anything parses it, skipping brackets inside strings. Anything over 8 deep is refused as `too_deep` on every machine, so the parser never meets deep input. The `RecursionError` catch is gone.

**Regression test.** The `[` × 3,000 case in `tests/test_schema.py` now expects `too_deep`. The old code returned `not_json` on Windows, so it fails there. A second test checks that brackets inside strings don't count.

## 2026-11-13: a test made a real live call once every civ had a culture

**What broke.** After I added culture prompts for Ironhold, Frostmark and Dunerunners, one full test run
made a real `claude -p` call on the operator's plan login: Ironhold, 1 tick, $0.075 notional. The project
rule is that tests make no live calls.

**How I found it.** The full suite went from passing to 1 failure: `test_the_runner_refuses_an_incomplete_llm_setup`,
which expected the runner to refuse `--llm live --llm-civs ironhold` because Ironhold had no culture. Its
error said the run folder `unused-run-folder` wasn't empty. That folder had appeared in the repository root,
and its `outputs.jsonl` held one `ok` reply with usage. On the earlier full run the refusal no longer fired,
so the runner went on, made the call and wrote the folder; the rerun then hit the folder.

The test leaned on a fact about the content (a civ without a culture) to keep the live path shut, and
nothing else stood between the test suite and `claude`.

**The fix.** The test now fakes a missing culture and writes into a temporary folder, and checks that no
folder was made. `tests/conftest.py` has an autouse guard: any test that starts a process named `claude`
fails at once. Tests that fake the subprocess set their own stand-in, which takes precedence. The stray
folder is kept, gitignored, in `runs/accidental-live-call-ironhold`.

**Regression test.** `test_a_test_that_reaches_a_live_call_fails_instead_of_calling` in
`tests/test_scheduler.py` builds a real `LiveAdapter` and calls it; the guard fails the test before any
process starts.

## 2026-11-14: every recorded cost was about 40 times too high

**What broke.** The cost meter, the viewer and the M19 and Phase 4 cost drafts all used the `total_cost_usd` that `claude -p` reports. For `claude-haiku-5-5` that figure is priced at Opus 5.5 rates. The M19 slice was recorded at $46.28 notional; at Haiku 5.5's list prices it cost $1.16.

**How I found it.** The operator asked what a mix of models would cost. At list prices a Haiku call with the token counts we had measured (about 6,200 output tokens) should cost about $0.004, but the recorded average was $0.17, a figure close to Opus pricing. A tiny live call printed its `modelUsage`: the model was `claude-haiku-5-5`, first party, with `costBasis: "unknown"`, and its $0.00954 matched Opus 5.5's 1-hour cache-write and output rates exactly. Recomputing every stored M19 row at Opus 5.5 rates reproduced each reported cost to the cent (0.0% worst row).

**The fix.** `fogline/pricing.py` holds list prices per model with the date they were read, and every call is priced from its token counts. The recorder now keeps the model asked for and the 1-hour/5-minute split of cache writes. The reported figure is kept as a record only. The cost drafts and ADR 0007 are corrected.

**Regression test.** `test_a_haiku_call_is_priced_from_the_table_not_from_what_claude_p_reported` in `tests/test_pricing.py` prices the tiny call's usage: Opus rates give the reported $0.00954, Haiku's give $0.00024. Locally, `test_the_m19_costs_claude_p_reported_are_opus_prices_to_the_cent` checks the stored M19 rows.

## 2026-11-14: dragging the year slider never moved the run

**What broke.** Dragging the slider in the viewer left the run on the year it was already showing. Nobody had noticed, because the arrow buttons, the keys and Play all worked.

**How I found it.** The time-lapse recorder sets the slider and fires its `input` event for each year, then waits for the year label to change. It timed out on the second year. Its error printed the page state: the label still read tick 0 and the slider was back at 0. In the handler, `stop()` ran first, and `stop()` calls `renderTime()`, which writes the current year back into the slider. Only then did the handler read `e.target.value`, which was by now the old year.

**The fix.** The handler reads the slider's value before it calls `stop()`.

**Regression test.** `test_the_slider_is_read_before_stopping_puts_it_back` in `tests/test_viewer.py` checks the handler reads the value before stopping. The recorder itself fails on the second year if it comes back.

## 2026-11-14: the mixed run billed an API key instead of the plan

**What broke.** The seed-3 mixed run stopped at tick 19 with every call failing, and its resume stopped the same way. Rulers are meant to run on the plan login (ADR 0007), but the run had been billing an API key the whole time, and the key's credit ran out.

**How I found it.** Every call returned "exit 1" with nothing else, because the adapter kept only stderr. Once it kept stdout too, the reason read "Credit balance is too low". Tiny calls of all three models then worked from my own shell but failed from the terminal tab the run was started in. The Windows user environment holds `ANTHROPIC_API_KEY`. A new PowerShell tab reads it, my shell had been started without it, and `claude -p` bills a key whenever one is set. The first 47 calls of the run (about $0.55 at list prices) went to the key.

**The fix.** The live adapter now starts `claude -p` with `ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN` removed from its environment, so a ruler call uses the plan login whatever shell starts the run. The run resumed on the plan and passed tick 20 without an error.

**Regression test.** `test_a_ruler_call_never_carries_an_api_key` in `tests/test_llm.py` sets both variables and checks that neither reaches the call, while other variables still do.

## 2026-11-14: the first finished mixed run crashed writing its summary

**What broke.** The seed-3 mixed run played all 400 ticks and saved its last snapshot, then stopped with a `TypeError` before writing `summary.json`. Every live run that reached its end would have done the same.

**How I found it.** The traceback ended in `Recorder.tokens()`, which adds up every field of each call's usage. Since the model roster, usage also keeps `answered_by`, the name of the model that answered, and adding a string to a number fails. The tests never caught it, because their fake calls had no model name in their usage, and the mixed run was the first live run to finish since the change.

**The fix.** The totals add only numbers and skip anything else. A resume replayed the stored calls and wrote the summary.

**Regression test.** `test_token_totals_skip_the_model_name_kept_with_usage` in `tests/test_llm.py` records two calls whose usage names the model, and checks the totals.

## 2026-11-18: rulers named their settlements and lost about 370 builds

**What broke.** All three mixed Phase 4 runs failed the 3-building-types check. Part of the cause was not the game at all: rulers wrote a settlement's name where a build order wants its id, and the engine refused every one as `not_own_settlement`.

**How I found it.** I counted every build order in the stored turns of seeds 1 to 3, with its refusal reason. About 370 were `not_own_settlement`. Grouping them by the settlement the ruler wrote showed names, never ids: Saltreach on seed 1 wrote "Tidewatch" 108 times for `saltreach-2`, Dunerunners "Mirage Rest" 49 times, Verdance "Thornwick" 48. The observation lists both `id` and `name` for each settlement, and the refusal names only the reason, so the rulers repeated the order turn after turn. The same count showed the other cause: timber at 0 from about tick 100, with lumber camps refused as `no_tile` once the one forest in reach was worked out.

**The fix.** With `settlement_names` in the run's manifest, the live layer swaps an own settlement's name for its id before the engine sees the reply (ADR 0013). New runs write the flag; the finished runs replay as they were.

**Regression test.** `tests/test_settlement_names.py`: a named build goes through with the flag on and is refused with it off; another civ's settlement name is refused exactly like a made-up one; the flag is written to the manifest and survives a resume.

## 2026-11-18: most trade offers were refused, and a civ out of timber could never trade

**What broke.** Even with settlement names fixed, Saltreach on the seed-1 rerun stopped at one building type. It had run out of timber, and every trade it tried was refused. Across all four mixed runs the engine refused 70 to 92% of trade offers as `no_caravan`.

**How I found it.** I counted every `offer_trade` and `respond_trade` in the stored turns with its refusal reason, then paired each `no_caravan` refusal with the caravans the ruler could see and, at snapshot ticks, the caravans the state held. On seed 3, in 47 of 54 sampled small offers refused this way, the civ's only caravan was reserved by an earlier offer, while the observation showed it `ready: true` with no reserved field. More than half the refused offers gave over 100 goods, which needs two caravans. Nothing in the prompt or schema mentioned caravans. Saltreach on the rerun made 39 offers, 33 asking for timber, and owned no caravan at any of them; a caravan cost 20 timber. The 394 `unknown_offer` refusals were mostly answers to trades already accepted (363), which do no harm.

**The fix.** After contact the schema explains caravans and reservation; own caravans show `reserved`; a caravan can be paid in stone when timber is short (ADR 0014).

**Regression test.** `tests/test_trade_legible.py`: the pre-contact prompts and schema match their old hashes; the post-contact schema explains caravans; a caravan shows reserved while an offer holds it and free once refused; a civ with 19 timber pays 20 stone; a civ short of both can't afford one; before contact a caravan is still an unknown unit.
