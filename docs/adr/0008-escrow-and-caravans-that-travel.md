# 0008: Trade goods sit in escrow and travel on caravans

## Decision
An offer moves the giver's goods out of its stockpile at once, into an escrow owned by the offer (`offer-<id>-give`), and reserves the caravans needed to carry them. Accepting does the same for the receiver's side (`offer-<id>-get`). On the next trade step each side's goods are loaded onto its caravans as cargo. The caravans walk the real map from the sender's settlement to the receiver's nearest one, and deliver on arrival, less the market fee, which is destroyed. Expiry or refusal returns the escrow. Every unit of every good moves through the ledger under a named rule (escrow, escrow return, loaded, trade delivery, market fee), so the conservation check covers goods in escrow and in transit.

A blueprint isn't a stock. It is minted as a logged event when it goes into escrow, carried by name on the leg, and either unlocks the tech on delivery or is destroyed as a logged event.

## Why
Trade is where Phase 5's raids will bite: rules 8 say a caravan can be raided and that there is no refund. That only means something if the goods are physically somewhere between the two civs for some ticks. An instant transfer would have nothing to raid, no delay for distance, and no reason for roads.

Escrow at the moment of offer stops a civ promising goods it then spends. Holding escrow under its own ledger owner keeps conservation exact: at every tick, each civ's stocks plus every offer's escrow plus every caravan's cargo add up to what production, consumption and the named trade rules say.

## Not chosen
- **Instant transfer on acceptance:** simpler, but there's nothing to raid, distance doesn't matter, and it contradicts rules 8.
- **A promise without escrow,** settled on delivery: a giver could spend the goods in between, and the engine would need a rule for a broken promise that the rules don't have.
- **One abstract leg instead of caravan units:** less code, but it would duplicate movement, and a leg couldn't be seen, met or raided like any other unit.

## What it cost
- Five new ledger rules and two new kinds of ledger owner, with the conservation check extended to cover them.
- New state that the hash and snapshots carry: units gained `reserved`, `cargo` and `leg`, and offers, prices and the map's crossing counts were added. A test saves a run with a caravan on the road, resumes it, and gets the same world.
- Before contact, `caravan`, `offer_trade` and `respond_trade` don't exist in the schema and answer like made-up orders. Their names alone would say there is someone to trade with.

## What I would not trust
- **Tracks:** they are counted per tile crossed, not per tile edge as rules 15.5 says. Two caravans crossing the same tile in different directions both count.
- **Prices:** only one-good-for-food trades set a price. A mixed trade sets none, so most values stay at base for a long time.
- **Caravans after delivery:** a caravan stays at the far settlement and has to be ordered home. Nothing yet stops a ruler leaving caravans scattered in foreign land.
