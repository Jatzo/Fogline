# 0006: One whitelisted observation, and a sea border round the map

## Decision
A ruler sees state through one function, `observation.observe()`. It builds the observation field by field from ground truth, and a nested whitelist (`observation.FIELDS`) lists every key it may emit. `check_fields()` runs on every observation and fails loudly on any other key or type, so a new field has to be added to the whitelist on purpose. Scripted bots get the same observation plus their own scratch memory as a second argument, which never enters the observation and never reaches an LLM.

What it shows, and how:
- Tiles are "dx,dy" from the civ's origin. Event and trigger text goes through one token mapper: absolute tiles become relative, the civ's own ids stay, a met civ's ids become its name, and any event that names an unmet civ is dropped. Own events and world events (comet, harsh winter) are shown; nobody else's.
- The observation is capped at 12,000 characters of canonical JSON (about 3,000 tokens). Over the cap, known tiles more than 6 from an own settlement or unit become counts per biome, then the oldest events go, then the farthest remaining tiles. Each trim is named in `elided`.
- There are no `messages` or `dossiers` keys before Phase 3. An empty list would tell a ruler that outsiders exist. For the same reason, `met`, `in_view` and `foreign_sites` appear only once the civ has met someone. The M8 version sent them empty from tick 0, and a key named `foreign_sites` gave the game away; the M13 prompt-leak check found it.

To hide where the map ends, the land is drawn on a 64 × 64 grid as before and then set inside 6 tiles of sea, so the map is 76 × 76. That is the largest sight radius (a stone fortress, 4) plus the 2-tile margin a move order may reach past known ground. So no unit sees past the sea to the edge, no move order can aim off the map, and the outer shore is coast like any other. A test ties the border to every sight radius in config. It was 4 tiles at first; the Phase 2 review found that a fortress on the outer shore could then see the last row.

## Why
The M5 brief was fog-honest but built ad hoc: nothing stopped a later change from adding a field that leaked. A whitelist builder makes a leak a deliberate edit that a test reads. Redacting the full state instead would mean every new state field leaks until someone remembers to hide it.

The fog tests don't search the text for the map size or the civ count as numbers. That kind of check both fires on stock values and misses arithmetic on the size. They are metamorphic instead: change what a civ can't see (other civs' stocks, stability, techs, populations and units; unseen biomes outside its land) and require its observation to be byte-identical. Over 10 seeds and 150 ticks of spiral scouts that covers about 2,000 observations, and a planted leak (population summed over all civs) fails at tick 16.

## Not chosen
- **Redact the state.** Copy it, delete what a civ must not see, send the rest. Short to write, but it fails open.
- **An inner sea border on the 64 map.** It drowned edge land: Dunerunners' timber ran out at 87 against 55 to 85, two civs missed the tree window, and outposts faced away less often. Padding keeps the land world as it was.
- **Padding without a coast.** It passed every tuned test, but a forest directly against open sea would only ever happen at the border, so it would mark the edge.

## What it cost
- The golden hash moved twice: the padding, and `seen_stocks` in the turn state (for `stock_changes`).
- The new shore opens the coast-gated tech for some civs, so a supplied builder now runs out of techs at tick 329 to 438 (seeds 1 to 5) and the tree window is 300 to 450 (rules 21).
- The fog fixture adds about 16 seconds to the suite.

## What I would not trust
- The token mapper recognises a civ by an id prefix. A future event whose detail uses a civ's display name, or a free-text word that happens to start with a civ id, would pass through unchecked. The metamorphic test only catches it if the leaked fact changes with hidden state.
- Node lists cover all own land, seen or not (rules 21), so a civ knows what lies on its unseen territory. That is a ruling, not a leak, but the metamorphic test has to leave own land alone because of it.
- The size cap counts characters, not tokens. The real prompt size is measured in M13.
