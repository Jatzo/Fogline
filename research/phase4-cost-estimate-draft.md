# Phase 4 cost estimate draft (numbers only)

An estimate for one live run: seed 1, 400 ticks, all five civs as live rulers on `claude-haiku-5-5` through `claude -p --safe-mode`, on the plan login. Costs are notional, not billed.

## Inputs

| Input | Value | Source |
|---|---|---|
| Calls per LLM civ per 100 ticks, before contact | 50.0 to 52.9 | `research/m19-cost-draft.md` |
| Cost per LLM civ per 100 ticks, before contact | $3.54 to $3.93 | same |
| Calls per LLM civ per 100 ticks, after contact | 80.2 to 92.5 | same |
| Cost per LLM civ per 100 ticks, after contact | $10.89 to $17.11 | same |
| First contact per civ, seed 1, 400-tick mock run | 46, 46, 54, 54, 77 | `runs/p4-mock-s1` (gitignored) |

The rates come from one seed with two live civs. The contact ticks come from mock rulers, which scout like the scripted bots.

## Estimate

| | Low | Middle | High |
|---|---|---|---|
| Ticks before contact, summed over 5 civs | 282 | 282 | 282 |
| Ticks after contact, summed over 5 civs | 1,718 | 1,718 | 1,718 |
| Calls | 1,519 | 1,629 | 1,738 |
| Notional cost | $197 | $251 | $305 |

Low uses the lowest rate in each column, high the highest, and middle the mean of the two. The ticks are taken from first contact plus 1, the first turn that could see it (rules 21).

## Mock run for comparison
`runs/p4-mock-s1`, seed 1, 400 ticks, five mock rulers: 1,334 calls (1,089 decide, 245 reflect), no cost. Phase 4 check: reached tick 400; divergence 0.0558; building types 3, 4, 2, 4 and 4 (Dunerunners, Frostmark, Ironhold, Saltreach, Verdance).
