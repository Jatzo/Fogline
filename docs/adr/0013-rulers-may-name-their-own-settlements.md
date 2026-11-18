# 0013: Rulers may name their own settlements, read as ids in the live layer

## Decision
Before the engine sees a ruler's reply, any action whose `settlement` is the name of one of the civ's own settlements ("Tidewatch") gets that settlement's id ("saltreach-2"). The match ignores case. Names come only from the civ's own observation. A name two of its settlements share, or a name that is also an id, is left as written. The swap lives in `llm.settlement_ids`, called by `make_ruler` for every live, mock and replayed ruler.

## Why
None of the three mixed Phase 4 runs passed the 3-building-types check. Reading every stored build order showed about 370 refused as `not_own_settlement` because the ruler wrote the name where the engine wants the id (Saltreach on seed 1 tried Tidewatch 108 times). The observation lists both, and the refusal says only `not_own_settlement`, so rulers kept trying. Every model did it.

Reading the name in the live layer keeps the engine, the state and the bots as they were. Doing it from the observation means it can't leak: the observation holds only the civ's own settlements, so another civ's name passes through and the engine refuses it with the same reason as a made-up one.

The first version sat behind a manifest flag so the three finished runs would still replay. ADR 0014 changes the observation and a rule in the same week, which ends exact replay of those runs under the new code anyway, so the flag went and runs now record the commit they ran at instead.

## Not chosen
- **An alias in the engine** (`actions.build` and `train_unit` accept names): one place, but it changes the rules for bots and every run.
- **A better refusal** (say "use the settlement id, for example saltreach-2"): keeps the interface strict and teaches the ruler, but each lesson costs a wasted turn, and rulers repeated refused orders hundreds of times even with the reason in front of them.
- **Swapping the name before the output is stored:** the stored raw text would no longer be what the model wrote.

## What it cost
One small function. Stored `turns.jsonl` replies show the id, not the name the model wrote; `outputs.jsonl` keeps the raw text.

## What I found
The mixed seed-1 rerun (`runs/p4-mix-s1-names`, 1,531 calls, $69.10) had no `not_own_settlement` refusals, against about 140 on the first seed-1 run, and 4 of 5 civs reached 3 building types, against 2. Saltreach stayed at 1: its timber ran out and every trade it tried was refused, which led to ADR 0014.

## What I would not trust
- One seed. The other two seeds have not been rerun with the swap.
- A ruler that names another civ's settlement still wastes the order, which is the point, but it learns nothing new.
