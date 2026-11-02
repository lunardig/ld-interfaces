"""M4b vectors (LD-PEC-004 Amendment 3, LD-PEC-008 §3.2): pass-through flow and part-load
energy. A chain fed at its producer's rate, a loop that settles, a loop that does not, a
feed below the consumer's turndown, and a melter whose power follows a part-load curve.

    python tools/m4b_vectors.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from m1_vectors import (JOINER_PORTS, R, S, SPLITTER_PORTS, Vector, base_entries, combine_process, kit, lot,  # noqa: E402
                        machine, split_process, tank)
from m2c_vectors import DAY, power_entries, power_plant  # noqa: E402

# Restart thresholds that make cycling visible: 20 mol of each gas.
GAS_BAND = {"h2": {"restart_at": "20000", "unit": "mmol"}, "o2": {"restart_at": "20000", "unit": "mmol"}}


def chain_entries(joiner_rated: dict, joiner_min: dict, lossy: bool = False, splitter_rated: dict | None = None) -> dict:
    """A splitter (2 H2O -> 2 H2 + O2) whose gases feed a joiner (the reverse) through
    their own tanks. `lossy`: the splitter takes 3 H2O per unit and leaves one as ice, so
    a loop through it loses a third each round."""
    e = base_entries()
    split = split_process("split-flow", "FLOW")
    if lossy:
        e["substances"] = e["substances"] + [{"substance_id": "h2o-s", "formula": {"h": "2", "o": "1"}, "phase": "solid", "quantity_unit": "mmol"}]
        split["stages"][0]["ops"][0]["vector"] = {"h2-g": "2", "h2o-l": "-3", "o2-g": "1", "h2o-s": "1"}
        split["ports"]["out"].append({"port": "ice", "accepts": ["h2o-s"]})
        split["edges"].append({"from": "stage:split", "to": "port:ice", "species": ["h2o-s"]})
    join = combine_process("join-flow")
    join["restart_thresholds"] = GAS_BAND
    ports = SPLITTER_PORTS + ([("ice", "MATERIAL", "OUT")] if lossy else [])
    joiner = machine("joiner", ["join-flow"], joiner_rated, JOINER_PORTS)
    joiner["min_stable_rate"] = joiner_min
    e["processes"] = [split, join]
    e["machines"] = [machine("splitter", ["split-flow"], splitter_rated or R(1, 1000), ports), joiner]
    t = tank("tank", 10**9)
    if lossy:
        t["accepts"] = t["accepts"] + ["h2o-s"]
    e["buffers"] = [t]
    e["products"] = [kit("splitter-kit", "MACHINE", "splitter"), kit("joiner-kit", "MACHINE", "joiner"), kit("tank-kit", "BUFFER", "tank")]
    return e


def chain_plant(v: Vector, loop: bool, lossy: bool = False) -> None:
    """Water -> splitter -> h2 and o2 tanks -> joiner -> water. `loop`: the joiner returns
    its water to the splitter's tank; otherwise to a tank of its own."""
    for k, a in [("splitter-kit", "splitter-1"), ("joiner-kit", "joiner-1"), ("tank-kit", "water-tank"), ("tank-kit", "h2-tank"),
                 ("tank-kit", "o2-tank"), ("tank-kit", "product-tank")] + ([("tank-kit", "ice-tank")] if lossy else []):
        v.install(0, k, a)
    v.feed(0, "c-water", "water-tank.io", "splitter-1.water")
    v.feed(0, "c-h2", "splitter-1.h2", "h2-tank.io")
    v.feed(0, "c-o2", "splitter-1.o2", "o2-tank.io")
    v.feed(0, "c-h2-in", "h2-tank.io", "joiner-1.h2")
    v.feed(0, "c-o2-in", "o2-tank.io", "joiner-1.o2")
    v.feed(0, "c-out", "joiner-1.water", ("water-tank" if loop else "product-tank") + ".io")
    if lossy:
        v.feed(0, "c-ice", "splitter-1.ice", "ice-tank.io")


def v31() -> list[Vector]:
    """The joiner is rated twice the splitter and could cycle on a 20 mol band. Instead it
    starts once the gases reach its pass-through margin and then runs at the splitter's
    rate, FED on both inputs, with the tanks holding a few mmol. A restore mid-run
    continues at the recorded rate."""
    e = chain_entries(R(2, 1000), R(1, 10**6))
    v = Vector("V-31", "fed-chain", "A consumer runs at its producer's rate through a buffer it alone draws from",
               ["LD-PEC-004 A3-1", "LD-PEC-004 A3-2", "LD-PEC-004 A3-5"], e,
               [lot("kits", "inventory", products={"splitter-kit": "1", "joiner-kit": "1", "tank-kit": "5"}),
                lot("water-1", "water-tank", {"h2o-l": "100000"})])
    chain_plant(v, loop=False)
    v.job(0, "job-split", "split-flow", "splitter-1", 40_000)
    v.job(0, "job-join", "join-flow", "joiner-1", 40_000)
    v.advance(10 * S)
    v.snapshot("running")
    v.advance(20 * S)
    v.restore("running")
    for t in (20 * S, 41 * S, 60 * S):
        v.advance(t)
    return [v]


def loop_plant(v: Vector, lossy: bool) -> None:
    """V-32 and V-33: the chain as a loop, plus a second splitter on its own large tank
    that also feeds the gas tanks, held to 1 wu/ms."""
    chain_plant(v, loop=True, lossy=lossy)
    v.install(0, "splitter-kit", "splitter-2")
    v.install(0, "tank-kit", "feed-tank")
    v.feed(0, "c-feed", "feed-tank.io", "splitter-2.water")
    v.feed(0, "c-h2-2", "splitter-2.h2", "h2-tank.io")
    v.feed(0, "c-o2-2", "splitter-2.o2", "o2-tank.io")
    if lossy:
        v.feed(0, "c-ice-2", "splitter-2.ice", "ice-tank.io")
    v.cmd(0, "SET_OPERATING_POLICY", machine_id="splitter-2", rate_setpoint=R(1, 1000))
    v.job(0, "job-feed", "split-flow", "splitter-2", 10**6)
    v.job(0, "job-join", "join-flow", "joiner-1", 10**6)
    v.job(0, "job-split", "split-flow", "splitter-1", 10**6)


def loop_lots(water: int) -> list[dict]:
    return [lot("kits", "inventory", products={"splitter-kit": "2", "joiner-kit": "1", "tank-kit": "7"}),
            lot("feed-1", "feed-tank", {"h2o-l": str(water)})]


def v32() -> list[Vector]:
    """A loop with an outside feed. Splitter-2 feeds the joiner, which returns its water to
    splitter-1's tank; splitter-1 feeds the joiner too. The joiner runs FED as soon as its
    margin allows; splitter-1's gas is at first extra stock in its tanks, and once the
    margin holds with both producers the joiner counts it. The loop settles where the
    machines bound it: the joiner FED at 5 wu/ms, splitter-1 at its rated 4 wu/ms on the
    water the joiner returns faster than it draws."""
    e = chain_entries(R(8, 1000), R(1, 10**6), splitter_rated=R(4, 1000))
    v = Vector("V-32", "fed-loop-settles", "Two jobs feeding each other settle on a common rate",
               ["LD-PEC-004 A3-2", "LD-PEC-004 A3-3"], e, loop_lots(10**6))
    loop_plant(v, lossy=False)
    for t in (1 * S, 5 * S, 20 * S):
        v.advance(t)
    return [v]


def v33() -> list[Vector]:
    """The same loop through splitters that leave a third of their water as ice. Each
    round returns two thirds of what splitter-1 takes, so from above the fixed point
    (joiner 3 wu/ms, splitter-1 2) is only approached. After the pass limit the passes run
    from below; their last, verified, holds both jobs FEED_UNSETTLED just under the fixed
    point, and gas builds slowly in the joiner's tanks."""
    e = chain_entries(R(8, 1000), R(1, 10**6), lossy=True, splitter_rated=R(4, 1000))
    v = Vector("V-33", "fed-loop-unsettled", "A loop whose rates do not settle falls back to cycling and says so",
               ["LD-PEC-004 A3-3"], e, loop_lots(10**6))
    loop_plant(v, lossy=True)
    for t in (1 * S, 5 * S, 20 * S):
        v.advance(t)
    return [v]


def v34() -> list[Vector]:
    """The joiner's turndown is 60 % of its rated 2 wu/ms, above the splitter's 1 wu/ms:
    it cannot run at the feed's rate, so it stops and restarts on its 20 mol band."""
    e = chain_entries(R(2, 1000), R(6, 5000))
    v = Vector("V-34", "feed-below-turndown", "A feed slower than the consumer's minimum stable rate leaves it cycling",
               ["LD-PEC-004 A3-1", "LD-PEC-006 §3.6.3"], e,
               [lot("kits", "inventory", products={"splitter-kit": "1", "joiner-kit": "1", "tank-kit": "5"}),
                lot("water-1", "water-tank", {"h2o-l": "100000"})])
    chain_plant(v, loop=False)
    v.job(0, "job-split", "split-flow", "splitter-1", 50_000)
    v.job(0, "job-join", "join-flow", "joiner-1", 50_000)
    for t in (30 * S, 60 * S):
        v.advance(t)
    return [v]


def v35() -> list[Vector]:
    """The 4 kW melter with a part-load curve: 10 % of rated power at no load, 60 % at half
    load, 100 % at rated. At half its rated rate it draws 2.4 kW, not 2 kW; the 400 W
    difference is heat at once. At night the battery gives at most 3 kW, which holds the
    melter at 68.75 % of rated on the curve's second segment (75 % without the curve)."""
    e = power_entries()
    melt = next(p for p in e["processes"] if p["process_id"] == "melt-ice")
    op = next(o for o in melt["stages"][0]["ops"] if o["op"] == "ENERGY")
    op["part_load"] = [{"load": R(0), "power": R(1, 10)}, {"load": R(1, 2), "power": R(3, 5)}, {"load": R(1), "power": R(1)}]
    battery = next(m for m in e["machines"] if m["blueprint_id"] == "battery")
    battery["energy_store"]["max_discharge"] = {"amount": R(3000), "unit": "w"}
    v = Vector("V-35", "part-load-energy", "A process's power follows its part-load curve; the loss is heat",
               ["LD-PEC-004 A3-4", "LD-PEC-006 §2.5"], e,
               [lot("kits", "inventory", products={"solar-kit": "1", "melter-kit": "1", "battery-kit": "1", "tank-kit": "2"}),
                lot("ice", "ice-tank", {"h2o-s": "1000000"})], environment=["irradiance"])
    power_plant(v, melt=True)
    v.cmd(0, "SET_OPERATING_POLICY", machine_id="melter-1", rate_setpoint=R(1, 4000))
    v.advance(30 * S)
    v.cmd(30 * S, "SET_OPERATING_POLICY", machine_id="melter-1", rate_setpoint=R(1, 2000))
    for t in (60 * S, DAY, DAY + 10 * S, DAY + 40 * S):
        v.advance(t)
    return [v]


def main() -> int:
    for v in v31() + v32() + v33() + v34() + v35():
        v.save()
    return 0


if __name__ == "__main__":
    sys.exit(main())
