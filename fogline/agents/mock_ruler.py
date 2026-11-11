"""The mock ruler: the scripted trader playing through the LLM path, with an LLM's bad habits.

It plays from the observation alone (its scratch memory stays on the adapter's side, like an LLM's
context), keeps a journal with set_note, and about one turn in ten adds an order that must fail,
drawn from its own random stream, so the rejection feedback runs in every mock game.
"""

from fogline import bots, rng
from fogline.config import Config
from fogline.turns import Decider, Reply

BAD_ORDERS = (
    {"kind": "set_research", "tech": "alchemy"},
    {"kind": "build", "settlement": "nowhere", "building": "farm"},
    {"kind": "move_unit", "unit": "nobody", "to": "0,0"},
    {"kind": "allocate_workers", "allocation": {"food": 200}},
    {"kind": "teleport"},
)
NOTE_EVERY = 8


def make(config: Config, civ_id: str, seed: int) -> Decider:
    builder = bots.make_trader(config, civ_id)  # the builder until contact, then it also trades

    def decide(observation: dict, scratch: dict) -> Reply:
        reply = dict(builder(observation, scratch))
        orders = list(reply.get("actions", []))
        tick = observation["tick"]
        if tick % NOTE_EVERY == 0:
            orders.append({"kind": "set_note", "text": f"Tick {tick}: {observation['population']} people, "
                                                       f"food {observation['stocks']['food']}."})
        for met in observation.get("met", []):
            if met["name"] not in scratch.get("greeted", []):  # one greeting per people met
                orders.append({"kind": "send_message", "to": met["name"],
                               "text": f"Greetings from {config.civ(civ_id).name}. We would trade."})
                reply.setdefault("memory", dict(scratch))["greeted"] = scratch.get("greeted", []) + [met["name"]]
        draw = rng.stream(seed, "mock", tick, civ_id, "bad-order")
        if draw.randrange(10) == 0:
            orders.append(dict(BAD_ORDERS[draw.randrange(len(BAD_ORDERS))]))
        reply["actions"] = orders[:config.max_actions_per_turn]
        return reply

    return decide
