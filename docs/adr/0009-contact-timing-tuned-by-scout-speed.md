# 0009: First contact is tuned by scout speed, not by moving the capitals

## Decision
Scouts move 8 tiles a tick, 10 with Pathfinding, up from 4 and 6. Nothing else about the world changes. With scripted spiral scouts, first contact now falls at a median of tick 55.5 over seeds 1 to 10, inside the 30 to 60 window PLAN section 3 asks for, and at 49.5 over seeds 11 to 20, which I held out while choosing.

## Why
Before the change, the median was tick 96, and 26 of 50 civs met no one in 150 ticks. Capitals sit on a pentagon 24 tiles from the centre, about 28 tiles apart, and a spiral at move 4 takes 60 to 100 ticks to cover half that distance.

Rules section 6 says to adjust start spacing first, then outpost placement, then scout move. I tried spacing first. A ring of 19 tiles gave a median of 47, and every seed made contact. But it reshapes every world, and the Phase 1 economy was tuned on those worlds: 10 tuned tests failed (when critical stocks run out, tree pace, the slice placement) and 11 more errored. Retuning that would reopen numbers that were measured and approved two phases ago. Outpost placement is also worldgen, so it would hit the same tests. Scout move is the last lever in the order, and it touches nothing but contact: every other test passed unchanged, and only the golden hash moved.

## Not chosen
- **A capital ring of 19 or 20:** median 47 (19) or 58 (20, with one seed never meeting), at the cost of retuning the Phase 1 economy. A ring of 18 or less fails worldgen's minimum path cost between capitals.
- **Scout move 6 or 7:** medians of 70.5 and 68.5, still outside the window.
- **Ring 19 with a smaller scout bump:** inside the window too, with the same retuning cost as ring 19 alone.
- **A smarter scripted scout:** it would move the measurement rather than the world. The test is defined by the scout that exists.

## What it cost
- The golden hash, and every bot run's contact timing. No economic number moved.
- Scouts are now twice as fast as anything else on the map, so a ruler can explore a lot of ground cheaply.

## What I would not trust
- **The response to scout move is noisy:** 6 gave 70.5, 7 gave 68.5 and 8 gave 55.5. Twenty seeds is a small sample, and 55.5 sits near the top of the window. The range per seed is 28 to 102.
- **LLM rulers won't scout like the spiral.** They may send scouts out sooner, later, or not at all, so their contact tick is reported in the Phase 4 check, not required.
- **The order in rules section 6 was put aside,** for the reason above. That is the operator's call to confirm.
