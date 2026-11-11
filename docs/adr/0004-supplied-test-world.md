# 0004: Tree pace and towns are measured in a supplied world

## Decision
The tree-pace test (rules 14) and the town test (rules 15.2) run the builder bot with `supply_floor` set. At the end of each tick, after events and before the tick counter moves on, every civ's food, timber, stone and metal below the floor is raised to it, logged under the ledger rule `supply`. The tree test uses a floor of 2,000 and the town test 50,000, on seed 1 with events off. The default is 0, which turns supply off. The run-out and decline tests (rules 4.7) stay unsupplied.

## Why
The rules asked one scripted, non-trading bot to do three things that can't all happen. It had to run out of its critical stock at tick 60 to 80 and decline (4.7), finish the tree by tick 300 to 400 (14), and grow an outpost to town by tick 200 (15.2). I measured why the last two failed. In isolation every civ's timber nets to about zero by tick 40, including civs not listed as short of it. On seed 1 Ironhold makes 7.7 timber a tick, burns 3.9 as fuel and pays 3.7 in upkeep arrears. The library and workshop then become ruins, scholars drop to 0, and research stops at tick 100 for every civ. Raising tech costs or lowering them changes nothing while the scholars are gone.

PLAN.md ties tree pace to a "well-run" civ, and in this game a well-run civ trades. Trade arrives in Phase 3, so until then the supply stands in for it.

## Not chosen
- **Make isolation sustain research.** Let the library and workshop join the buildings that never become ruins, and take timber off tech costs. Easy, but it weakens the hard scarcity in 4.7, which is the pressure the whole experiment is about.
- **Move both tests to Phase 3.** Honest, but Phase 1 would ship with no check on tech costs or growth at all, and the numbers would drift until then.
- **Top up only each civ's listed short stocks.** Closest to what trade would bring, but most civs still froze, because timber runs dry everywhere.
- **Include luxury.** A luxury stock lifts stability, and stability scales every line's output, so the tree pace would quietly depend on a stability gift.
- **A one-off lump of 50,000 at the start.** Capitals grew to 370 people, ate the lump by about tick 150 and starved back down.

## What it cost
Two rule changes came out of the measuring, both approved: growth may run on a food store of 40 ticks of eating (4.1), because food-short civs never grow on their own farms; and era points doubled, because a supplied builder finished the tree by tick 200 to 250.

## What I'd not trust
- The town test at 50,000 shows food-short civs growing on supplied food plus bot housing. That is what imported food would do, but it isn't proof that any real trade deal brings that much.
- Supplied runs on seeds 1 to 5 give almost the same tree and town ticks, so five seeds count for about one run, not five. The tests use seed 1 only.
- The supply fires on every basic stock for every civ (seed 1, floor 2,000, 400 ticks: 1,742 to 16,545 per stock). The tree test therefore measures research once the basics are covered, not the economy that would cover them.
