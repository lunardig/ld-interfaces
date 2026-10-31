"""Writes the M2c vectors (LD-PEC-005 §8.6): ASSEMBLE, energy stores, idle power and the
closed alpha loop.

    python tools/m2c_vectors.py

Execution vectors get expected/ from an engine through ld-sdk's tools/run_vectors.py
--write. Admission vectors carry their expected verdict here. All stay DRAFT until the
reference evaluator reproduces them.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from m1_vectors import H, R, S, Vector, kit, lot, machine  # noqa: E402
from m2_vectors import (EXTENT, DepositVector, admission, bin_, chain_entries, deposit, elements, energy, proc,  # noqa: E402
                        substances, units, with_energy)

# ---------------------------------------------------------------- shared entries

IRON, RUTILE = "fe-s", "tio2-s"
HOPPER_IRON, HOPPER_SCRAP = 1_800_000, 100_000  # mmol of iron per hopper (LD-PEC-005 §8.4)


def m2c_substances() -> list[dict]:
    return substances() + with_energy([
        {"substance_id": IRON, "formula": {"fe": "1"}, "phase": "solid", "quantity_unit": "mmol"},
        {"substance_id": RUTILE, "formula": {"ti": "1", "o": "2"}, "phase": "solid", "quantity_unit": "mmol"},
    ])


def battery_machine(capacity_j: int = 100_000, charge_w: int = 5000, discharge_w: int = 5000, eff=(9, 10)) -> dict:
    m = machine("battery", [], R(1, S), [("power", "ELECTRICAL", "IN")])
    m["energy_store"] = {"capacity": {"amount": R(capacity_j), "unit": "j"}, "max_charge": {"amount": R(charge_w), "unit": "w"},
                         "max_discharge": {"amount": R(discharge_w), "unit": "w"}, "charge_efficiency": R(*eff), "heat_sink": "battery-heat"}
    return m


def reduce_ilmenite() -> dict:
    """FeTiO3 + H2 -> Fe + TiO2 + H2O, a batch with a 600 s dwell (LD-PEC-005 §8.4)."""
    p = proc("reduce-ilmenite", [("ilmenite", ["fetio3-s"]), ("h2", ["h2-g"])], [("iron", [IRON]), ("rutile", [RUTILE]), ("water", ["h2o-l"])], [
        {"op": "REACT", "vector": {"fetio3-s": "-1", "h2-g": "-1", IRON: "1", RUTILE: "1", "h2o-l": "1"}, "extent": EXTENT},
        {"op": "WORK", "a": R(1), "b": R(0)},
        energy(50),
        {"op": "DWELL", "duration_us": {"kind": "const", "value": R(600 * S)}},
    ])
    p["mode"] = "BATCH"
    return p


def fabricate_hopper() -> dict:
    """One hopper kit per unit from 1 900 mol of iron; 100 mol is scrap."""
    stage = "fabricate"
    return {
        "process_id": "fabricate-hopper", "pset_version": "0", "mode": "BATCH",
        "extent": {"unit": "count", "min": "1", "max": "100"},
        "ports": {"in": [{"port": "iron", "accepts": [IRON]}], "out": [{"port": "scrap", "accepts": [IRON]}]},
        "stages": [{"stage_id": stage, "ops": [
            {"op": "ASSEMBLE", "product": "hopper-kit", "count": EXTENT, "materials": {IRON: str(HOPPER_IRON + HOPPER_SCRAP)},
             "scrap": {IRON: str(HOPPER_SCRAP)}, "scrap_stream": "offcuts"},
            {"op": "WORK", "a": R(1), "b": R(0)},
            {"op": "ENERGY", "mode": "PER_WORK", "dir": "DRAW", "amount": R(2_000_000), "unit": "j", "heat_sink": "waste-heat"},
        ]}],
        "edges": [{"from": "port:iron", "to": f"stage:{stage}"}, {"from": f"stage:{stage}.offcuts", "to": "port:scrap"}],
        "failure_disposition": {stage: "RETAIN"}, "restart_thresholds": {}, "constants": {},
    }


def m2c_units() -> list[dict]:
    return units() + [{"unit_id": "count", "dimension": "count", "scale": R(1)}]


# ---------------------------------------------------------------- P-04: ASSEMBLE admission

def p04() -> None:
    entries = {"elements": elements(), "units": m2c_units(), "substances": m2c_substances(), "processes": [fabricate_hopper()],
               "machines": [machine("fabricator", ["fabricate-hopper"], R(1, 600 * S), [("iron", "MATERIAL", "IN"), ("scrap", "MATERIAL", "OUT")])],
               "products": [hopper_kit()], "buffers": [bin_("hopper", ["regolith"], 5000, "kg-reg")]}
    admission("P-04a", "assemble-balanced", "ASSEMBLE whose materials equal embodied plus scrap is accepted",
              ["LD-PEC-003 §4 ASSEMBLE", "LD-PEC-003 §11 P-04", "LD-PEC-005 §8.1"], entries, {"verdict": "ACCEPTED"})
    bad = copy.deepcopy(entries)
    p = bad["processes"][0]
    p["process_id"] = "fabricate-from-nothing"
    p["stages"][0]["ops"][0]["materials"] = {IRON: str(HOPPER_IRON)}
    bad["machines"][0]["processes"] = ["fabricate-from-nothing"]
    admission("P-04b", "assemble-unbalanced", "ASSEMBLE that would embody more than it uses after scrap is rejected",
              ["LD-PEC-003 §4 ASSEMBLE", "LD-PEC-003 §11 P-04", "LD-PEC-005 §8.1"], bad,
              {"verdict": "REJECTED", "failed_check": "ELEMENT_BALANCE", "subject": "fabricate-from-nothing",
               "detail": "fe-s in (1800000) must equal embodied (1800000) plus scrap (100000)"})


def hopper_kit() -> dict:
    k = kit("hopper-kit", "BUFFER", "hopper")
    k["embodied"] = {IRON: str(HOPPER_IRON)}
    return k


# ---------------------------------------------------------------- V-01: stoichiometry

def v01() -> list[Vector]:
    """LD-PEC-001 V-01: 4 pmol of water gives exactly 4 pmol of hydrogen and 2 of oxygen."""
    pm = [{"unit_id": "pmol", "dimension": "amount", "scale": R(1, 10**12)}, {"unit_id": "wu", "dimension": "work", "scale": R(1)},
          {"unit_id": "j", "dimension": "energy", "scale": R(1)}, {"unit_id": "w", "dimension": "power", "scale": R(1)}]
    subs = [{"substance_id": s, "formula": f, "phase": ph, "quantity_unit": "pmol"} for s, f, ph in
            [("h2o-l", {"h": "2", "o": "1"}, "liquid"), ("h2-g", {"h": "2"}, "gas"), ("o2-g", {"o": "2"}, "gas")]]
    split = proc("electrolyze-water", [("water", ["h2o-l"])], [("h2", ["h2-g"]), ("o2", ["o2-g"])], [
        {"op": "REACT", "vector": {"h2-g": "2", "h2o-l": "-2", "o2-g": "1"}, "extent": EXTENT},
        {"op": "WORK", "a": R(1), "b": R(0)},
    ], unit="pmol")
    e = {"elements": [x for x in elements() if x["element_id"] in ("h", "o")], "units": pm, "substances": subs, "processes": [split],
         "machines": [machine("electrolyzer", ["electrolyze-water"], R(1, S), [("water", "MATERIAL", "IN"), ("h2", "MATERIAL", "OUT"), ("o2", "MATERIAL", "OUT")])],
         "products": [kit("electrolyzer-kit", "MACHINE", "electrolyzer"), kit("tank-kit", "BUFFER", "tank")],
         "buffers": [{"template_id": "tank", "accepts": ["h2o-l", "h2-g", "o2-g"], "capacity": {"amount": "1000", "unit": "pmol"}}],
         "connections": [{"template_id": "pipe", "kind": "FEED", "throughput": R(1), "unit": "pmol", "delay_us": "0"}], "environment": []}
    v = Vector("V-01", "stoichiometry", "Electrolysis of 4 pmol of water yields exactly 4 pmol of hydrogen and 2 pmol of oxygen",
               ["LD-PEC-001 §11 V-01"], e,
               [lot("kits", "inventory", products={"electrolyzer-kit": "1", "tank-kit": "3"}), lot("water", "water-tank", {"h2o-l": "4"})])
    for k, a in [("electrolyzer-kit", "electrolyzer-1"), ("tank-kit", "water-tank"), ("tank-kit", "h2-tank"), ("tank-kit", "o2-tank")]:
        v.install(0, k, a)
    for c, f, t in [("c-w", "water-tank.io", "electrolyzer-1.water"), ("c-h", "electrolyzer-1.h2", "h2-tank.io"), ("c-o", "electrolyzer-1.o2", "o2-tank.io")]:
        v.feed(0, c, f, t)
    v.job(0, "job-split", "electrolyze-water", "electrolyzer-1", 2)
    v.advance(10 * S)
    return [v]


# ---------------------------------------------------------------- power: V-06, V-11, V-22

DAY = 100 * S
SHORT_DAY = {"function_id": "irradiance", "unit": "w-m2", "period_us": str(2 * DAY),
             "segments": [{"start_us": "0", "value": R(1361)}, {"start_us": str(DAY), "value": R(0)}]}


def small_solar() -> dict:
    """10 kW while the sun is up."""
    return {
        "process_id": "generate-solar", "pset_version": "0", "mode": "FLOW",
        "extent": {"unit": "s", "min": "0", "max": "1000000000000"},
        "ports": {"in": [], "out": []},
        "stages": [{"stage_id": "generate", "ops": [
            {"op": "REQUIRE", "predicate": {"kind": "environment", "function_id": "irradiance", "min": R(100), "max": R(2000)}},
            {"op": "WORK", "a": R(1), "b": R(0)},
            {"op": "ENERGY", "mode": "PER_WORK", "dir": "PRODUCE", "amount": R(10_000), "unit": "j", "heat_sink": "waste-heat"},
        ]}],
        "edges": [], "failure_disposition": {"generate": "RETAIN"}, "restart_thresholds": {}, "constants": {},
    }


def heater() -> dict:
    """Melts ice at 8 J/mmol: 4 kW at 500 mmol/s."""
    return proc("melt-ice", [("ice", ["h2o-s"])], [("water", ["h2o-l"])], [
        {"op": "PHASE", "from": "h2o-s", "to": "h2o-l", "quantity": EXTENT},
        {"op": "WORK", "a": R(1), "b": R(0)},
        energy(8),
    ], unit="mmol")


def power_entries(idle_w: int = 0) -> dict:
    melter = machine("melter", ["melt-ice"], R(1, 2000), [("ice", "MATERIAL", "IN"), ("water", "MATERIAL", "OUT"), ("power", "ELECTRICAL", "IN")])
    if idle_w:
        melter["idle_power"] = {"amount": R(idle_w), "unit": "w"}
        melter["idle_heat_sink"] = "idle-heat"
    return {"elements": elements(), "units": units(), "substances": substances(), "processes": [small_solar(), heater()],
            "machines": [machine("solar-array", ["generate-solar"], R(1, S), [("power", "ELECTRICAL", "OUT")]), melter, battery_machine()],
            "products": [kit("solar-kit", "MACHINE", "solar-array"), kit("melter-kit", "MACHINE", "melter"), kit("battery-kit", "MACHINE", "battery"),
                         kit("tank-kit", "BUFFER", "tank")],
            "buffers": [bin_("tank", ["h2o-s", "h2o-l"], 10**9, "mmol")],
            "connections": [{"template_id": "pipe", "kind": "FEED", "throughput": R(1, 100), "unit": "mmol", "delay_us": "0"}],
            "environment": [SHORT_DAY]}


def power_plant(v: Vector, melt: bool) -> None:
    for k, a in [("solar-kit", "solar-1"), ("melter-kit", "melter-1"), ("battery-kit", "battery-1"), ("tank-kit", "ice-tank"), ("tank-kit", "water-tank")]:
        v.install(0, k, a)
    v.feed(0, "c-ice", "ice-tank.io", "melter-1.ice")
    v.feed(0, "c-water", "melter-1.water", "water-tank.io")
    v.job(0, "job-sun", "generate-solar", "solar-1", 10**9, priority=100)
    if melt:
        v.job(0, "job-melt", "melt-ice", "melter-1", 10**8, priority=10)


def v06() -> list[Vector]:
    """By day the sun covers the 4 kW melter and charges the battery at 5 kW (4.5 kW
    stored). At sunset the battery carries the melter until it is empty, and not a
    microsecond longer; the melter resumes at sunrise. A restore mid-discharge replays."""
    v = Vector("V-06", "electrical-interruption", "A job on battery power stops exactly when the store empties and resumes when generation returns",
               ["LD-PEC-001 §11 V-06", "LD-PEC-005 §8.2"], power_entries(),
               [lot("kits", "inventory", products={"solar-kit": "1", "melter-kit": "1", "battery-kit": "1", "tank-kit": "2"}),
                lot("ice", "ice-tank", {"h2o-s": "1000000"})], environment=["irradiance"])
    power_plant(v, melt=True)
    for t in (30 * S, DAY, DAY + 10 * S):
        v.advance(t)
    v.snapshot("night")
    v.advance(DAY + 60 * S)
    v.restore("night")
    for t in (DAY + 60 * S, 2 * DAY, 2 * DAY + 30 * S):
        v.advance(t)
    return [v]


def v22() -> list[Vector]:
    """An idle melter draws 2 kW. The battery fills by day and carries the idle draw for
    50 s of night; then the melter shows as unpowered until sunrise."""
    v = Vector("V-22", "idle-drain", "Idle draw is served after jobs; at night it drains the battery, then the machine shows as unpowered",
               ["LD-PEC-005 §8.2", "LD-PEC-005 §8.3"], power_entries(idle_w=2000),
               [lot("kits", "inventory", products={"solar-kit": "1", "melter-kit": "1", "battery-kit": "1", "tank-kit": "2"})], environment=["irradiance"])
    power_plant(v, melt=False)
    for t in (30 * S, DAY, DAY + 40 * S, DAY + 60 * S, 2 * DAY + 10 * S):
        v.advance(t)
    return [v]


def v11() -> list[Vector]:
    """LD-PEC-001 V-11. A store returning more than it takes in is rejected at load. Two
    charged batteries and no generation never gain energy: with a load they only drain,
    and they never charge each other. A removed battery keeps its charge in its kit."""
    e = power_entries()
    over = copy.deepcopy(e)
    over["machines"][2]["energy_store"]["charge_efficiency"] = R(3, 2)
    over["machines"][2]["blueprint_id"] = "perpetual-battery"
    over["products"][2]["installs_as"]["template"] = "perpetual-battery"
    admission("V-11a", "perpetuum-mobile-store", "An energy store with charge efficiency above 1 is rejected",
              ["LD-PEC-001 §11 V-11", "LD-PEC-005 §8.2"], over,
              {"verdict": "REJECTED", "failed_check": "ENERGY_BALANCE", "subject": "perpetual-battery", "detail": "charge_efficiency must be in (0, 1]"})
    charged = [dict(lot(f"battery-{i}", "inventory", products={"battery-kit": "1"}), charge=R(50_000)) for i in (1, 2)]
    v = Vector("V-11b", "stores-never-gain", "Two charged batteries and no generation: they drain into a load and never charge each other",
               ["LD-PEC-001 §11 V-11", "LD-PEC-005 §8.2"], e,
               [lot("kits", "inventory", products={"melter-kit": "1", "tank-kit": "2"}), lot("ice", "ice-tank", {"h2o-s": "1000000"})] + charged)
    v.cmd(0, "INSTALL", lot_id="battery-1", product="battery-kit", location="pad-a", as_id="battery-a")
    v.cmd(0, "INSTALL", lot_id="battery-2", product="battery-kit", location="pad-a", as_id="battery-b")
    for k, a in [("melter-kit", "melter-1"), ("tank-kit", "ice-tank"), ("tank-kit", "water-tank")]:
        v.install(0, k, a)
    v.advance(50 * S)
    v.feed(60 * S, "c-ice", "ice-tank.io", "melter-1.ice")
    v.feed(60 * S, "c-water", "melter-1.water", "water-tank.io")
    v.job(60 * S, "job-melt", "melt-ice", "melter-1", 10**8)
    v.cmd(70 * S, "PAUSE", job_id="job-melt")
    v.advance(70 * S)
    v.cmd(71 * S, "REMOVE", target_id="battery-a")
    v.advance(200 * S)
    return [v]


# ---------------------------------------------------------------- V-23: the closed loop

def loop_entries() -> dict:
    e = chain_entries()
    e["units"] = m2c_units()
    e["substances"] = m2c_substances()
    e["processes"] += [reduce_ilmenite(), fabricate_hopper()]
    e["machines"] += [
        machine("reactor", ["reduce-ilmenite"], R(1, 1000), [("ilmenite", "MATERIAL", "IN"), ("h2", "MATERIAL", "IN"), ("iron", "MATERIAL", "OUT"),
                                                              ("rutile", "MATERIAL", "OUT"), ("water", "MATERIAL", "OUT"), ("power", "ELECTRICAL", "IN")]),
        machine("fabricator", ["fabricate-hopper"], R(1, 600 * S), [("iron", "MATERIAL", "IN"), ("scrap", "MATERIAL", "OUT"), ("power", "ELECTRICAL", "IN")]),
    ]
    e["products"] = [p for p in e["products"] if p["product_id"] != "hopper-kit"] + [
        hopper_kit(), kit("reactor-kit", "MACHINE", "reactor"), kit("fabricator-kit", "MACHINE", "fabricator"),
        kit("iron-bin-kit", "BUFFER", "iron-bin"), kit("rutile-bin-kit", "BUFFER", "rutile-bin")]
    e["buffers"] = [b for b in e["buffers"] if b["template_id"] not in ("ilmenite-bin", "tank")] + [
        bin_("ilmenite-bin", ["fetio3-s"], 5_000_000, "mmol"), bin_("tank", ["h2o-l", "h2-g", "o2-g"], 10**8, "mmol"),
        bin_("iron-bin", [IRON], 5_000_000, "mmol"), bin_("rutile-bin", [RUTILE], 5_000_000, "mmol")]
    return e


def v23() -> list[Vector]:
    """Dig, sort, melt, split, reduce, fabricate, install. A hopper made from the claim's
    own iron is installed; elements are conserved at every event, embodied iron included."""
    kits = {"excavator-kit": "1", "beneficiator-kit": "1", "melter-kit": "1", "electrolyzer-kit": "1", "solar-array-kit": "1", "reactor-kit": "1",
            "fabricator-kit": "1", "hopper-kit": "1", "ice-bin-kit": "1", "ilmenite-bin-kit": "1", "tank-kit": "3", "iron-bin-kit": "2", "rutile-bin-kit": "1"}
    v = DepositVector("V-23", "closed-loop", "The alpha loop: a hopper fabricated from iron reduced from the claim's own ilmenite is installed",
                      ["LD-PEC-005 §8.4", "LD-PEC-005 §8.5", "Alpha MVP §3"], loop_entries(),
                      [lot("kits", "inventory", products=kits)], environment=["irradiance"], deposits=[deposit("icy-crater", 10**9)])
    for k, a in [("solar-array-kit", "solar-1"), ("excavator-kit", "excavator-1"), ("beneficiator-kit", "beneficiator-1"), ("melter-kit", "melter-1"),
                 ("electrolyzer-kit", "electrolyzer-1"), ("reactor-kit", "reactor-1"), ("fabricator-kit", "fabricator-1"),
                 ("hopper-kit", "hopper-1"), ("ice-bin-kit", "ice-bin-1"), ("ilmenite-bin-kit", "ilmenite-bin-1"), ("tank-kit", "water-tank"),
                 ("tank-kit", "h2-tank"), ("tank-kit", "o2-tank"), ("iron-bin-kit", "iron-bin-1"), ("iron-bin-kit", "scrap-bin"),
                 ("rutile-bin-kit", "rutile-bin-1")]:
        v.install(0, k, a)
    for c, f, t in [("c-dig", "icy-crater.face", "excavator-1.face"), ("c-hop", "excavator-1.out", "hopper-1.io"),
                    ("c-feed", "hopper-1.io", "beneficiator-1.feed"), ("c-ice", "beneficiator-1.ice", "ice-bin-1.io"),
                    ("c-ilm", "beneficiator-1.ilmenite", "ilmenite-bin-1.io"), ("c-melt", "ice-bin-1.io", "melter-1.ice"),
                    ("c-water", "melter-1.water", "water-tank.io"), ("c-split", "water-tank.io", "electrolyzer-1.water"),
                    ("c-h2", "electrolyzer-1.h2", "h2-tank.io"), ("c-o2", "electrolyzer-1.o2", "o2-tank.io"),
                    ("c-r-ilm", "ilmenite-bin-1.io", "reactor-1.ilmenite"), ("c-r-h2", "h2-tank.io", "reactor-1.h2"),
                    ("c-r-fe", "reactor-1.iron", "iron-bin-1.io"), ("c-r-ti", "reactor-1.rutile", "rutile-bin-1.io"),
                    ("c-r-w", "reactor-1.water", "water-tank.io"), ("c-fab", "iron-bin-1.io", "fabricator-1.iron"),
                    ("c-scrap", "fabricator-1.scrap", "scrap-bin.io")]:
        v.feed(0, c, f, t)
    v.job(0, "job-sun", "generate-solar", "solar-1", 10**9, priority=100)
    v.job(0, "job-dig", "excavate", "excavator-1", 40, priority=10)
    v.job(0, "job-sort", "beneficiate", "beneficiator-1", 3600, priority=10)
    v.job(0, "job-melt", "melt-ice", "melter-1", 10**8, priority=10)
    v.job(0, "job-split", "electrolyze-water", "electrolyzer-1", 1_000_000, priority=10)
    for i in range(4):
        v.job(0, f"job-reduce-{i + 1}", "reduce-ilmenite", "reactor-1", 475_000, priority=5)
    v.job(0, "job-fab", "fabricate-hopper", "fabricator-1", 1, priority=5)
    for h in range(1, 6):
        v.advance(h * H)
    v.cmd(5 * H, "INSTALL", lot_id="job-fab.out", product="hopper-kit", location="pad-a", as_id="hopper-2")
    v.advance(5 * H + S)
    return [v]


def main() -> int:
    p04()
    for v in v01() + v06() + v22() + v11() + v23():
        v.save()
    return 0


if __name__ == "__main__":
    sys.exit(main())
