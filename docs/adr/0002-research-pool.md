# 0002: One research pool per civ

## Decision
Each civ keeps one pool of research points (`research.points_milli`). Scholars add to it every tick. A tech completes when the pool covers its points and the stockpile covers its resources; the resources are paid at that moment, through the ledger, and the points come out of the pool. Switching tech keeps the pool. Points earned while no tech is chosen are lost, unless the tree is finished, when each whole point becomes prestige.

## Why
Rulers will switch research when things change, and an LLM ruler will switch more than a script would. With one pool a switch costs nothing and needs no bookkeeping, so the state stays small and the rule is easy to explain in an observation ("you have 63 of 80 points").

Paying resources at completion, not when research is chosen, means a ruler who picks a tech and then changes their mind hasn't lost 20 timber. If the points are there but the stock isn't, the tech waits and the pool keeps growing, so a shortage delays research without wasting it.

Losing points with no tech chosen stops a civ from banking hundreds of points and then unlocking several techs in one tick, which would make the tree pace test (rules 14) meaningless.

## Not chosen
- **Progress kept per tech.** Closer to "scholars work on one thing", but switching then strands half-finished progress. That needs a rule for what happens to it, and the observation has to show every partial tech.
- **Resources paid when research is chosen.** Simple, but switching then either refunds (another ledger path) or wastes stock, and both are easy to get wrong.
- **Keep points with no tech chosen.** Friendlier to a forgetful ruler, but it lets the pool become a bank.

## What I'd watch
A ruler that finishes a tech's points but can't pay keeps adding points it can spend straight after, so the next tech can come very quickly once stock arrives. If the tree pace test in M6 shows bursts like that, cap the pool at the current tech's cost.
