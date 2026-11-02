"""Level-switch vectors (LD-PEC-004 Amendment 4): stop levels beside restart levels, and
levels given as fractions of the connected buffer's capacity.

    python tools/m4d_vectors.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from m1_vectors import (JOINER_PORTS, R, S, SPLITTER_PORTS, Vector, base_entries, combine_process, kit, lot,  # noqa: E402
                        machine, split_process, tank)

# The splitter's gas outputs on a level switch: restart when 60 % of the tank is free
# (40 % full), stop when only 20 % is free (80 % full). Headroom is what an output measures.
def gas_band() -> dict:
    return {port: {"restart_fraction": R(3, 5), "stop_fraction": R(1, 5)} for port in ("h2", "o2")}


def band_entries(gas_tank: int) -> dict:
    """A splitter at 1 wu/ms filling gas tanks of `gas_tank` mmol, which a joiner at
    0.5 wu/ms drains. Water and product tanks are large."""
    e = base_entries()
    split = split_process("split-flow", "FLOW", thresholds=gas_band())
    join = combine_process("join-flow")
    e["processes"] = [split, join]
    e["machines"] = [machine("splitter", ["split-flow"], R(1, 1000), SPLITTER_PORTS),
                     machine("joiner", ["join-flow"], R(1, 2000), JOINER_PORTS)]
    e["buffers"] = [tank("tank", 10**9), tank("gas-tank", gas_tank)]
    e["products"] = [kit("splitter-kit", "MACHINE", "splitter"), kit("joiner-kit", "MACHINE", "joiner"),
                     kit("tank-kit", "BUFFER", "tank"), kit("gas-tank-kit", "BUFFER", "gas-tank")]
    return e


def band_plant(v: Vector) -> None:
    for k, a in [("splitter-kit", "splitter-1"), ("joiner-kit", "joiner-1"), ("tank-kit", "water-tank"),
                 ("gas-tank-kit", "h2-tank"), ("gas-tank-kit", "o2-tank"), ("tank-kit", "product-tank")]:
        v.install(0, k, a)
    for c, f, t in [("c-water", "water-tank.io", "splitter-1.water"), ("c-h2", "splitter-1.h2", "h2-tank.io"),
                    ("c-o2", "splitter-1.o2", "o2-tank.io"), ("c-h2-in", "h2-tank.io", "joiner-1.h2"),
                    ("c-o2-in", "o2-tank.io", "joiner-1.o2"), ("c-out", "joiner-1.water", "product-tank.io")]:
        v.feed(0, c, f, t)


def v36() -> list[Vector]:
    """The splitter fills a 10 mol hydrogen tank at 2 mmol/ms while the joiner drains it at
    1 mmol/ms. The splitter stops with STOP_LEVEL when the tank is 80 % full (2,000 mmol
    free), not when it is full, and restarts when it is down to 40 % (6,000 mmol free):
    one cycle every 12 s or so instead of one per unit. A restore mid-band continues it."""
    v = Vector("V-36", "stop-level-band", "A producer runs a hysteresis band between a stop level and a restart level",
               ["LD-PEC-004 A4-1", "LD-PEC-004 A4-2"], band_entries(10_000),
               [lot("kits", "inventory", products={"splitter-kit": "1", "joiner-kit": "1", "tank-kit": "2", "gas-tank-kit": "2"}),
                lot("water-1", "water-tank", {"h2o-l": "200000"})])
    band_plant(v)
    v.job(0, "job-split", "split-flow", "splitter-1", 100_000)
    v.job(0, "job-join", "join-flow", "joiner-1", 100_000)
    v.advance(10 * S)
    v.snapshot("in-band")
    v.advance(30 * S)
    v.restore("in-band")
    for t in (30 * S, 60 * S):
        v.advance(t)
    return [v]


def v37() -> list[Vector]:
    """V-36's processes with 40 mol gas tanks: the same fractions now mean 32,000 and 16,000
    mmol, so the band is four times as long. The splitter's water input keeps a heel: it
    stops at 30 mol (stop_at) and would restart at 60 mol (restart_at). The water switch
    latches only when water trips it, so the hydrogen restart at 48 s is not held back by
    water between the two levels. At 61 s the water trips; with nothing refilling it, the
    splitter stays stopped on STOP_LEVEL and 30 mol remain."""
    e = band_entries(40_000)
    split = e["processes"][0]
    split["restart_thresholds"]["water"] = {"restart_at": "60000", "stop_at": "30000", "unit": "mmol"}
    v = Vector("V-37", "fraction-levels-and-heel", "Fractional levels scale with the buffer; an input stop level keeps a heel",
               ["LD-PEC-004 A4-1", "LD-PEC-004 A4-2"], e,
               [lot("kits", "inventory", products={"splitter-kit": "1", "joiner-kit": "1", "tank-kit": "2", "gas-tank-kit": "2"}),
                lot("water-1", "water-tank", {"h2o-l": "120000"})])
    band_plant(v)
    v.job(0, "job-split", "split-flow", "splitter-1", 100_000)
    v.job(0, "job-join", "join-flow", "joiner-1", 100_000)
    for t in (30 * S, 90 * S):
        v.advance(t)
    return [v]


def main() -> int:
    for v in v36() + v37():
        v.save()
    return 0


if __name__ == "__main__":
    sys.exit(main())
