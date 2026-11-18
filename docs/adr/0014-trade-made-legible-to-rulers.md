# 0014: Trade is explained to rulers after contact, held caravans show, and a caravan can be paid in stone

## Decision
Three changes, made together:
1. **Trade is explained, after contact only.** Once a civ has met someone, the reply schema describes `offer_trade`, `respond_trade` and the caravan in `train_unit`: one free caravan per 100 goods sent (200 with Carts), for offering and for accepting; the caravans stay reserved until the goods are delivered, the offer is refused or it expires; what a caravan costs. The numbers come from the config. Before contact the system prompt and schema are byte for byte what they were, and a test holds them to the old hashes.
2. **A held caravan says so.** In the observation, each of the civ's own caravans carries `reserved: true|false`. Other units carry no such field, and a civ has no caravans before contact, so nothing about trade shows before then.
3. **A caravan can be paid in stone.** It costs 10 food and 20 timber as before, or 10 food and 20 stone when the civ can't pay the timber (`alt_cost` in the config).

Runs now record `git_commit` and `dirty` in their manifest, and `--llm replay` refuses outputs whose manifest config hash differs from the code's.

## Why
Rulers try to trade a great deal, and the engine refused most of it: `no_caravan` on 532 of 581 offers on seed 1, 517 of 700 on seed 2, 501 of 631 on seed 3 and 277 of 394 on the seed-1 rerun. The stored outputs gave three causes:
- No prompt or schema text mentioned caravans at all.
- A caravan held by an earlier offer showed `ready: true`. On seed 3, in 47 of 54 sampled small offers refused this way, the civ's only caravan was held by an earlier offer.
- More than half the refused offers gave over 100 goods, which needs two caravans.

And Saltreach on the rerun made 39 offers, 33 of them asking for timber, and owned no caravan at any of them. A caravan cost 20 timber, so a civ out of timber couldn't build the caravan that would bring timber in. Trade is the game's answer to the run-outs in rules 4.7, so with trade blocked the run-outs had no answer.

## Not chosen
- **Per-feature manifest flags,** so the finished runs replay under new code: the stone cost is a rule in the config, which changes the config hash and ends exact replay of those runs whatever is flagged. Recording the commit lets any run replay at its own code instead.
- **The `reserved` field on every unit:** simpler, but it would put a trade word into every observation before contact.
- **Caravans paid in food alone:** moves the deadlock to the civs that run out of food (Ironhold, Dunerunners).
- **Telling rulers to trade more, or to build more kinds of building:** it would steer the behaviour the project measures.

## What it cost
- The golden hash moved. With the config hash taken out, the seed-1 state at tick 200 is identical before and after.
- `runs/p4-live-s1`, the all-Haiku run stopped at tick 40, can no longer be resumed (its config hash is the old one). The operator chose to let it go.
- The three finished mixed runs replay only at their own commits: seeds 1 to 3 at 4cb4d7b and earlier, the seed-1 rerun at 9cfca95 with uncommitted changes (it predates the commit field).

## What I would not trust
- Deadlocks remain: a civ under 20 of both timber and stone, under 10 food, or with 2 people or fewer at home can't build a caravan.
- Explaining trade doesn't make a ruler trade well. A trade also needs a partner who accepts.
