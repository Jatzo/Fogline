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
