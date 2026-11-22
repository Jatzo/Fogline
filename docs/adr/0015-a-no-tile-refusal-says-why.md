# 0015: A no_tile build refusal says why

## Decision
A refusal may carry a `detail`: one or two sentences the engine writes, capped at 200 characters. Only a build refused as `no_tile` sets it for now. The `reason` stays `no_tile`, so the bots, the evidence pack and the Phase 4 check read refusals exactly as before.

`construction.why_no_tile` writes the detail from the civ's own land only:
- for a tile hint, why that tile wasn't used: not in your territory; in another of your settlements' land; outside the footprint; already has a building; or not the ground the building needs;
- for a lumber camp or a mine, the settlement's own nodes of that kind and what is wrong with each (used up, has a building), or that it has none;
- for other buildings, that the settlement has no free tile of the ground they need;
- then which of the civ's settlements have room for that building, or that none do.

A hint off the civ's own land gets "not in your territory" and nothing about what is on it. Tiles are shown relative to the civ's origin, as in the observation. The detail states facts only; it never suggests another building.

For Saltreach on seed 1, tick 56, asking for a lumber camp at Tidewatch on tile 10,-6, the detail reads: "Tile 10,-6 is not a forest node with stock left and no building on it. Tidewatch has no forest node in its land. None of your settlements has room for a lumber_camp."

## Why
On the seed-1 trade run (`runs/p4-mix-s1-trade`) Saltreach built a mine and nothing else in 400 ticks, and failed the Phase 4 building check. It had timber, 1,481 of it received by trade. Every build it asked for after the mine was a lumber camp, refused 21 times as `no_tile`. A lumber camp needs a forest node with stock left in the settlement's land. Saltreach's one forest node was used up and already held its starting camp, and its other three settlements had none. Its notes show it reading forest ground as somewhere a camp could go ("Tried lumber camp at Tidewatch on forest 10,-6"). The bare `no_tile` couldn't tell it a wrong tile from nowhere in this settlement, or nowhere at all.

## Not chosen
- **Finer reason codes** (`no_node`, `node_used_up`, `hint_not_own`, ...): changes every count by reason in the evidence pack, the bots' retry rules and comparisons with the finished runs. A free-text detail keeps `reason` stable.
- **Listing the buildings the civ could place:** closer to advice, and the project measures what rulers choose to build. The detail says what this building needs and where it fits, nothing about others.
- **Writing the detail when the observation is built, not when the build is refused:** it would keep older runs resumable, but by then the land may have changed and the text could be wrong about the moment of refusal.

## What it cost
- Stored refusals are part of the world state, so a run started before this change can't resume across a turn that holds a `no_tile` refusal. All Phase 4 runs have finished; `runs/p4-live-s1` already couldn't resume.
- Observations grow by up to 200 characters for each explained refusal. Refusals are the last thing cut when an observation is over budget.

## What I would not trust
- The `build_failed ... no_tile` event, raised when a queued build later finds no tile, is still unexplained.
- "Has room" runs the same placement as a real build, at the moment of refusal. Room can be gone by the time the ruler asks again.
- Saying why doesn't make a ruler build something else. Whether Saltreach changes course is for the next run to show.
