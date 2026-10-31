"""M3b process builders and vectors (LD-PEC-006 §3.2): energy content per substance, the
Gibbs cap, load-following generators, the regenerative fuel cell and the fission reactor.
ld-sdk's alpha catalog imports the builders.

    python tools/m3b_vectors.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from m1_vectors import R, S, Vector, kit, lot, machine  # noqa: E402
from m2_vectors import EXTENT, admission, bin_, elements  # noqa: E402
from m2c_vectors import DAY, power_entries, power_plant  # noqa: E402

FRESH, SPENT = "fuel-fresh", "fuel-spent"
URANIUM = {"element_id": "u", "symbol": "U", "molar_mass": R(238029, 1000)}


def fuel_substances(fresh_j_per_mmol: int) -> list[dict]:
    """Fresh and spent fuel: one empirical formula (UO2), so elements balance; energy content
    differs by the recoverable fission energy. Fission products and the ~0.1 % mass
    defect are recorded simplifications (LD-PEC-006 §3.2.3)."""
    return [
        {"substance_id": FRESH, "formula": {"u": "1", "o": "2"}, "phase": "solid", "quantity_unit": "mmol", "enthalpy": R(fresh_j_per_mmol)},
        {"substance_id": SPENT, "formula": {"u": "1", "o": "2"}, "phase": "solid", "quantity_unit": "mmol", "enthalpy": R(0)},
    ]


def fuel_cell(produce_j: int = 286) -> dict:
    """2 H2 + O2 -> 2 H2O per unit (1 mmol of reaction). It releases 571.66 J; the Gibbs
    energy caps electricity at 474.26 J; it sells 286 J, about half the enthalpy, and the
    rest is heat. Follows load."""
    return {
        "process_id": "fuel-cell", "pset_version": "0", "mode": "FLOW", "dispatch": "FOLLOW_LOAD",
        "extent": {"unit": "rxn-mmol", "min": "0", "max": "1000000000000"},
        "ports": {"in": [{"port": "h2", "accepts": ["h2-g"]}, {"port": "o2", "accepts": ["o2-g"]}], "out": [{"port": "water", "accepts": ["h2o-l"]}]},
        "stages": [{"stage_id": "cell", "ops": [
            {"op": "REACT", "vector": {"h2-g": "-2", "o2-g": "-1", "h2o-l": "2"}, "extent": EXTENT},
            {"op": "WORK", "a": R(1), "b": R(0)},
            {"op": "ENERGY", "mode": "PER_WORK", "dir": "PRODUCE", "amount": R(produce_j), "unit": "j", "heat_sink": "waste-heat"},
        ]}],
        "edges": [{"from": "port:h2", "to": "stage:cell"}, {"from": "port:o2", "to": "stage:cell"}, {"from": "stage:cell", "to": "port:water"}],
        "failure_disposition": {"cell": "RETAIN"}, "restart_thresholds": {}, "constants": {},
    }


def fission(produce_j: int) -> dict:
    """Fresh fuel to spent fuel, one mmol per unit; sells `produce_j` of the energy drop as
    electricity and the rest goes to the reactor's radiator. Follows load."""
    return {
        "process_id": "fission", "pset_version": "0", "mode": "FLOW", "dispatch": "FOLLOW_LOAD",
        "extent": {"unit": "mmol", "min": "0", "max": "1000000000000"},
        "ports": {"in": [{"port": "fuel", "accepts": [FRESH]}], "out": [{"port": "spent", "accepts": [SPENT]}]},
        "stages": [{"stage_id": "core", "ops": [
            {"op": "REACT", "vector": {FRESH: "-1", SPENT: "1"}, "extent": EXTENT},
            {"op": "WORK", "a": R(1), "b": R(0)},
            {"op": "ENERGY", "mode": "PER_WORK", "dir": "PRODUCE", "amount": R(produce_j), "unit": "j", "heat_sink": "reactor-heat"},
        ]}],
        "edges": [{"from": "port:fuel", "to": "stage:core"}, {"from": "stage:core", "to": "port:spent"}],
        "failure_disposition": {"core": "RETAIN"}, "restart_thresholds": {}, "constants": {},
    }


def gas_store() -> dict:
    return bin_("gas-store", ["h2-g", "o2-g"], 5_000_000_000, "mmol")


# ---------------------------------------------------------------- admission

def admissions() -> None:
    e = power_entries()
    e["processes"] = e["processes"] + [fuel_cell(500)]
    e["machines"] = e["machines"] + [machine("cell", ["fuel-cell"], R(1, 50_000), [("h2", "MATERIAL", "IN"), ("o2", "MATERIAL", "IN"), ("water", "MATERIAL", "OUT"),
                                                                                  ("power", "ELECTRICAL", "OUT")])]
    admission("P-14", "fuel-cell-over-gibbs", "A fuel cell selling more electricity than the Gibbs energy released is rejected, though within the enthalpy",
              ["LD-PEC-006 §3.2.1"], e, {"verdict": "REJECTED", "failed_check": "ENERGY_BALANCE", "subject": "fuel-cell",
                                         "detail": "produces more electrical energy than its reactions' Gibbs energy allows"})
    e2 = copy.deepcopy(e)
    e2["processes"][-1] = fuel_cell(600)
    admission("P-15", "fuel-cell-over-enthalpy", "A fuel cell selling more energy than its reaction releases is rejected",
              ["LD-PEC-006 §3.2.1", "LD-PEC-003 P-13"], e2, {"verdict": "REJECTED", "failed_check": "ENERGY_BALANCE", "subject": "fuel-cell",
                                                             "detail": "produces or absorbs more energy than it draws or its reactions release"})


# ---------------------------------------------------------------- execution

def v26() -> list[Vector]:
    """A fuel cell carries the night. By day the sun runs the 4 kW melter and fills the
    battery; at dusk the battery takes over until it is empty; then the fuel cell follows
    the load, burning only the hydrogen the melter needs. At dawn it drops back to its
    minimum. Stored energy, heat, held energy and chemical energy add up at every step."""
    e = power_entries()
    e["processes"] = e["processes"] + [fuel_cell()]
    e["machines"] = e["machines"] + [machine("cell", ["fuel-cell"], R(1, 50_000), [("h2", "MATERIAL", "IN"), ("o2", "MATERIAL", "IN"), ("water", "MATERIAL", "OUT"),
                                                                                  ("power", "ELECTRICAL", "OUT")])]
    e["products"] = e["products"] + [kit("cell-kit", "MACHINE", "cell"), kit("gas-kit", "BUFFER", "gas-store")]
    e["buffers"] = [bin_("tank", ["h2o-s", "h2o-l"], 10**9, "mmol"), gas_store()]
    v = Vector("V-26", "fuel-cell-night", "A load-following fuel cell carries the night after the battery; it burns only what the load needs",
               ["LD-PEC-006 §3.2.1", "LD-PEC-006 §3.2.2", "LD-PEC-006 §3.2.4"], e,
               [lot("kits", "inventory", products={"solar-kit": "1", "melter-kit": "1", "battery-kit": "1", "tank-kit": "2", "cell-kit": "1", "gas-kit": "2"}),
                lot("ice", "ice-tank", {"h2o-s": "1000000"}), lot("h2", "h2-store", {"h2-g": "10000"}), lot("o2", "o2-store", {"o2-g": "5000"})],
               environment=["irradiance"])
    power_plant(v, melt=True)
    for k, a in [("cell-kit", "cell-1"), ("gas-kit", "h2-store"), ("gas-kit", "o2-store")]:
        v.install(0, k, a)
    for c, f, t in [("c-h2", "h2-store.io", "cell-1.h2"), ("c-o2", "o2-store.io", "cell-1.o2"), ("c-cw", "cell-1.water", "water-tank.io")]:
        v.feed(0, c, f, t)
    v.job(0, "job-cell", "fuel-cell", "cell-1", 10**9, priority=50)
    for t in (30 * S, DAY, DAY + 20 * S, DAY + 40 * S, 2 * DAY - S, 2 * DAY + 20 * S):
        v.advance(t)
    return [v]


def v27() -> list[Vector]:
    """A 10 kW fission reactor follows load, down to a 2 kW minimum. By day the sun covers
    the melter and the reactor idles at its minimum; its surplus is waste heat. At night
    it carries the melter. Fuel turns into spent fuel; the energy drop is electricity plus
    reactor heat."""
    e = power_entries()
    e["elements"] = elements() + [URANIUM]
    e["substances"] = e["substances"] + fuel_substances(1_000_000)
    e["processes"] = e["processes"] + [fission(250_000)]
    reactor = machine("reactor", ["fission"], R(1, 25_000_000), [("fuel", "MATERIAL", "IN"), ("spent", "MATERIAL", "OUT"), ("power", "ELECTRICAL", "OUT")])
    reactor["min_stable_rate"] = R(1, 125_000_000)
    e["machines"] = [m for m in e["machines"] if m["blueprint_id"] != "battery"] + [reactor]
    e["products"] = [p for p in e["products"] if p["product_id"] != "battery-kit"] + [kit("reactor-kit", "MACHINE", "reactor"), kit("cask-kit", "BUFFER", "cask")]
    e["buffers"] = e["buffers"] + [bin_("cask", [FRESH, SPENT], 1_000_000, "mmol")]
    v = Vector("V-27", "fission-follows-load", "A fission reactor follows load down to its minimum; surplus at the minimum is waste heat; fuel energy is conserved",
               ["LD-PEC-006 §3.2.1", "LD-PEC-006 §3.2.2", "LD-PEC-006 §3.2.3"], e,
               [lot("kits", "inventory", products={"solar-kit": "1", "melter-kit": "1", "tank-kit": "2", "reactor-kit": "1", "cask-kit": "2"}),
                lot("ice", "ice-tank", {"h2o-s": "1000000"}), lot("fuel", "fuel-cask", {FRESH: "100"})], environment=["irradiance"])
    for k, a in [("solar-kit", "solar-1"), ("melter-kit", "melter-1"), ("tank-kit", "ice-tank"), ("tank-kit", "water-tank"), ("reactor-kit", "reactor-1"),
                 ("cask-kit", "fuel-cask"), ("cask-kit", "spent-cask")]:
        v.install(0, k, a)
    for c, f, t in [("c-ice", "ice-tank.io", "melter-1.ice"), ("c-water", "melter-1.water", "water-tank.io"), ("c-fuel", "fuel-cask.io", "reactor-1.fuel"),
                    ("c-spent", "reactor-1.spent", "spent-cask.io")]:
        v.feed(0, c, f, t)
    v.job(0, "job-sun", "generate-solar", "solar-1", 10**9, priority=100)
    v.job(0, "job-fission", "fission", "reactor-1", 10**9, priority=50)
    v.job(0, "job-melt", "melt-ice", "melter-1", 10**8, priority=10)
    for t in (50 * S, DAY, DAY + 50 * S, 2 * DAY, 2 * DAY + 50 * S):
        v.advance(t)
    return [v]


def main() -> int:
    admissions()
    for v in v26() + v27():
        v.save()
    return 0


if __name__ == "__main__":
    sys.exit(main())
