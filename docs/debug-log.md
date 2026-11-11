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
