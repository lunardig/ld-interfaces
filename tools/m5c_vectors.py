"""Early-end settlement (LD-PEC-004 Amendment 8, F-47): a FLOW job that ends early settles
the energy it holds.

    python tools/m5c_vectors.py

V-30 covers a generator: its cancelled fission job completes the unit it had sold energy
for, burning that unit's fuel. V-30b covers a consumer: a melter cancelled half-way
through a unit turns the energy it drew for that half unit into heat.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from m1_vectors import S, Vector, lot  # noqa: E402
from m2c_vectors import power_entries, power_plant  # noqa: E402


def v30b() -> list[Vector]:
    """By day the melter runs at 500 mmol/s, a unit (1 mmol) every 2 ms. Cancelled 1 ms
    into a unit, it has drawn 4 J for half a unit: that becomes heat, and the unit's
    work is lost. Elements and energy balance throughout."""
    v = Vector("V-30b", "early-end-consumer", "A consumer cancelled mid-unit turns the energy it drew for that unit into heat",
               ["LD-PEC-004 A8", "LD-PEC-006 §3.2.1"], power_entries(),
               [lot("kits", "inventory", products={"solar-kit": "1", "melter-kit": "1", "battery-kit": "1", "tank-kit": "2"}),
                lot("ice", "ice-tank", {"h2o-s": "1000000"})], environment=["irradiance"])
    power_plant(v, melt=True)
    t = 10 * S + 1000
    v.advance(10 * S)
    v.cmd(t, "CANCEL", job_id="job-melt")
    v.advance(t + S)
    return [v]


def main() -> int:
    for v in v30b():
        v.save()
    return 0


if __name__ == "__main__":
    sys.exit(main())
