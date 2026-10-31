"""Writes the M2 exit-test worlds (LD-PEC-005 §8.5) into property/: random valid reaction
networks, partitions with random fractions, flow and batch jobs, assemblies, and
battery-powered plants, from a fixed seed list so a failure is reproducible.

    python tools/m2c_property.py

They have no expected outputs. ld-engine's property tests advance each world in random
steps and check, at every step, that element totals (lots, deposits, sinks, held lots
and embodied material) never change, and that stored energy plus heat equals the
energy the batteries started with: these worlds have no generation.
"""
from __future__ import annotations

import random
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ld  # noqa: E402
from m1_vectors import R, S, Vector, kit, lot, machine  # noqa: E402
from m2_vectors import EXTENT, bin_, elements  # noqa: E402
from m2c_vectors import IRON, RUTILE, battery_machine, m2c_substances, m2c_units  # noqa: E402

PROPERTY = ld.ROOT / "property"
SEEDS = list(range(1, 25))

# Balanced building blocks; random integer combinations of them are balanced too.
BASIS = [
    {"h2o-l": -2, "h2-g": 2, "o2-g": 1},
    {"fetio3-s": -1, "h2-g": -1, IRON: 1, RUTILE: 1, "h2o-l": 1},
    {"h2-g": -2, "o2-g": -1, "h2o-l": 2},
    {"fetio3-s": -1, "h2-g": -1, IRON: 1, RUTILE: 1, "h2o-l": 1, "o2-g": 0},
]
ALL = ["h2o-l", "h2-g", "o2-g", "fetio3-s", IRON, RUTILE]


class PropertyWorld(Vector):
    def __init__(self, seed: int, *a, **kw):
        super().__init__(f"PROP-{seed:02d}", "world", *a, **kw)
        self.dir = PROPERTY / f"PROP-{seed:02d}"


def reaction(rng: random.Random) -> dict[str, int]:
    while True:
        v: dict[str, int] = {}
        for _ in range(rng.randint(1, 2)):
            k = rng.randint(1, 3)
            for sp, c in rng.choice(BASIS).items():
                v[sp] = v.get(sp, 0) + k * c
        v = {sp: c for sp, c in v.items() if c != 0}
        if any(c < 0 for c in v.values()) and any(c > 0 for c in v.values()):
            return v


def process(rng: random.Random, pid: str) -> tuple[dict, list[str], list[str]]:
    vec = reaction(rng)
    ins = sorted(sp for sp, c in vec.items() if c < 0)
    outs = sorted(sp for sp, c in vec.items() if c > 0)
    mode = rng.choice(["FLOW", "BATCH"])
    ops = [{"op": "REACT", "vector": {sp: str(c) for sp, c in vec.items()}, "extent": EXTENT},
           {"op": "WORK", "a": R(rng.randint(1, 3)), "b": R(0)},
           {"op": "ENERGY", "mode": "PER_WORK", "dir": "DRAW", "amount": R(rng.randint(1, 20)), "unit": "j", "heat_sink": "waste-heat"},
           {"op": "WEAR", "per": "WORK", "amount": R(1, 1000)}]
    edges = [{"from": f"port:in-{i}", "to": "stage:s"} for i in range(len(ins))]
    out_ports = [{"port": "out", "accepts": ALL}]
    if rng.random() < 0.7:
        d = rng.choice([3, 7, 10, 11])
        n = rng.randint(1, d - 1)
        fr = {sp: R(rng.randint(0, n), d) for sp in outs}
        ops.insert(1, {"op": "PARTITION", "input": "pool", "residue": "rest", "outputs": [{"stream": "cut", "fractions": fr}]})
        out_ports.append({"port": "rest", "accepts": ALL})
        edges += [{"from": "stage:s.cut", "to": "port:out"}, {"from": "stage:s.rest", "to": "port:rest"}]
    else:
        edges.append({"from": "stage:s", "to": "port:out"})
    return ({"process_id": pid, "pset_version": "0", "mode": mode, "extent": {"unit": "rxn-mmol", "min": "0", "max": "1000000000000"},
             "ports": {"in": [{"port": f"in-{i}", "accepts": [sp]} for i, sp in enumerate(ins)], "out": out_ports},
             "stages": [{"stage_id": "s", "ops": ops}], "edges": edges,
             "failure_disposition": {"s": "RETAIN"}, "restart_thresholds": {}, "constants": {}}, ins, [p["port"] for p in out_ports])


def assembly(rng: random.Random) -> dict:
    scrap = rng.randint(0, 50)
    return {"process_id": "assemble", "pset_version": "0", "mode": "BATCH", "extent": {"unit": "count", "min": "1", "max": "100"},
            "ports": {"in": [{"port": "in-0", "accepts": [IRON]}], "out": [{"port": "out", "accepts": ALL}]},
            "stages": [{"stage_id": "s", "ops": [
                {"op": "ASSEMBLE", "product": "widget", "count": EXTENT, "materials": {IRON: str(100 + scrap)}, "scrap": {IRON: str(scrap)},
                 "scrap_stream": "offcuts"},
                {"op": "WORK", "a": R(1), "b": R(0)},
                {"op": "ENERGY", "mode": "PER_WORK", "dir": "DRAW", "amount": R(rng.randint(1, 50)), "unit": "j", "heat_sink": "waste-heat"}]}],
            "edges": [{"from": "port:in-0", "to": "stage:s"}, {"from": "stage:s.offcuts", "to": "port:out"}],
            "failure_disposition": {"s": "RETAIN"}, "restart_thresholds": {}, "constants": {}}


def world(seed: int) -> PropertyWorld:
    rng = random.Random(seed)
    procs, plants = [], []
    for i in range(rng.randint(1, 3)):
        p, ins, outs = process(rng, f"p{i}")
        procs.append(p)
        plants.append((p, ins, outs))
    if rng.random() < 0.5:
        procs.append(assembly(rng))
        plants.append((procs[-1], [IRON], ["out"]))
    machines, kits, lots = [], {"bin-kit": 0, "battery-kit": 0}, []
    for p, ins, outs in plants:
        ports = [(f"in-{i}", "MATERIAL", "IN") for i in range(len(ins))] + [(o, "MATERIAL", "OUT") for o in outs] + [("power", "ELECTRICAL", "IN")]
        m = machine(f"m-{p['process_id']}", [p["process_id"]], R(rng.randint(1, 5), rng.choice([1000, 10_000, 100_000])), ports, lanes=rng.randint(1, 2))
        if rng.random() < 0.4:
            m["idle_power"] = {"amount": R(rng.randint(1, 500)), "unit": "w"}
        machines.append(m)
        kits[f"m-{p['process_id']}-kit"] = 1
    machines.append(battery_machine(capacity_j=rng.randint(50_000, 500_000), charge_w=rng.randint(100, 5000),
                                    discharge_w=rng.randint(100, 20_000), eff=(rng.randint(5, 10), 10)))
    entries = {"elements": elements(), "units": m2c_units(), "substances": m2c_substances(), "processes": procs, "machines": machines,
               "products": [kit(f"{m['blueprint_id']}-kit", "MACHINE", m["blueprint_id"]) for m in machines if m["blueprint_id"] != "battery"]
               + [kit("battery-kit", "MACHINE", "battery"), kit("bin-kit", "BUFFER", "bin"),
                  {"product_id": "widget", "embodied": {IRON: "100"}}],
               "buffers": [bin_("bin", ALL, 10**10, "mmol")],
               "connections": [{"template_id": "pipe", "kind": "FEED", "throughput": R(rng.randint(1, 100), 10), "unit": "mmol", "delay_us": "0"}],
               "environment": []}
    v = PropertyWorld(seed, "Random world for the M2 exit property tests", ["LD-PEC-005 §8.5"], entries, lots)
    n_batt = rng.randint(1, 2)
    for b in range(n_batt):
        lots.append(dict(lot(f"batt-{b}", "inventory", products={"battery-kit": "1"}), charge=R(rng.randint(1, 400_000))))
        v.cmd(0, "INSTALL", lot_id=f"batt-{b}", product="battery-kit", location="pad", as_id=f"battery-{b}")
    nb = 0
    for k, (p, ins, outs) in enumerate(plants):
        mid = f"m{k}"
        v.install(0, f"m-{p['process_id']}-kit", mid)
        for i, sp in enumerate(ins):
            b = f"bin-{nb}"
            nb += 1
            lots.append(lot(f"fill-{b}", b, {sp: str(rng.randint(1000, 1_000_000))}))
            v.install(0, "bin-kit", b)
            v.feed(0, f"c-{b}", f"{b}.io", f"{mid}.in-{i}")
        for o in outs:
            b = f"bin-{nb}"
            nb += 1
            v.install(0, "bin-kit", b)
            v.feed(0, f"c-{b}", f"{mid}.{o}", f"{b}.io")
        for j in range(rng.randint(1, 3)):
            target = rng.randint(1, 5) if p["process_id"] == "assemble" else rng.randint(1, 50_000)
            v.job(0, f"j{k}-{j}", p["process_id"], mid, target, priority=rng.randint(0, 3))
    lots.insert(0, lot("kits", "inventory", products={k: str(n) for k, n in {**kits, "bin-kit": nb}.items() if n}))
    t = 0
    for _ in range(rng.randint(5, 15)):
        t += rng.randint(1, 120 * S)
        v.advance(t)
        if rng.random() < 0.2:
            v.cmd(t, "PAUSE", job_id=f"j0-0")
        if rng.random() < 0.2:
            v.cmd(t, "RESUME", job_id=f"j0-0")
    return v


def main() -> int:
    if PROPERTY.exists():
        shutil.rmtree(PROPERTY)
    for s in SEEDS:
        world(s).save()
    return 0


if __name__ == "__main__":
    sys.exit(main())
