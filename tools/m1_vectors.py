"""Writes the inputs of the M1 execution vectors (alpha MVP §5: V-02, V-03, V-04, V-05,
V-07, V-09, V-10 from LD-PEC-001 §11).

    python tools/m1_vectors.py

Each vector directory gets vector.json, catalog/, genesis.json, commands.jsonl and
script.jsonl. Expected outputs (expected/) are produced by an engine through the
conformance harness in ld-sdk (tools/run_vectors.py --write) and stay DRAFT until the
reference evaluator reproduces them byte for byte.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ld  # noqa: E402

VECTORS = ld.ROOT / "vectors"
S = 1_000_000
H = 3600 * S


def R(n: int, d: int = 1) -> dict:
    from math import gcd
    g = gcd(n, d)
    return {"n": str(n // g), "d": str(d // g)}


def write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- catalog pieces
def base_entries() -> dict[str, list[dict]]:
    return {
        "elements": [
            {"element_id": "h", "symbol": "H", "molar_mass": R(1008, 1000)},
            {"element_id": "o", "symbol": "O", "molar_mass": R(15999, 1000)},
        ],
        "units": [
            {"unit_id": "mmol", "dimension": "amount", "scale": R(1, 1000)},
            {"unit_id": "rxn-mmol", "dimension": "amount", "scale": R(1, 1000)},
            {"unit_id": "wu", "dimension": "work", "scale": R(1)},
            {"unit_id": "j", "dimension": "energy", "scale": R(1)},
            {"unit_id": "w", "dimension": "power", "scale": R(1)},
            {"unit_id": "w-m2", "dimension": "power", "scale": R(1)},
        ],
        "substances": [
            {"substance_id": "h2o-l", "formula": {"h": "2", "o": "1"}, "phase": "liquid", "quantity_unit": "mmol"},
            {"substance_id": "h2-g", "formula": {"h": "2"}, "phase": "gas", "quantity_unit": "mmol"},
            {"substance_id": "o2-g", "formula": {"o": "2"}, "phase": "gas", "quantity_unit": "mmol"},
        ],
        "processes": [],
        "machines": [],
        "products": [],
        "buffers": [],
        "connections": [
            {"template_id": "pipe", "kind": "FEED", "throughput": R(1000), "unit": "mmol", "delay_us": "0"},
            {"template_id": "belt", "kind": "CONVEYOR", "throughput": R(1, 1000), "unit": "mmol", "delay_us": str(2 * S)},
        ],
        "environment": [],
    }


def split_process(pid: str, mode: str, ops_extra: list[dict] | None = None, thresholds: dict | None = None) -> dict:
    """2 H2O -> 2 H2 + O2, one work quantum per unit of extent."""
    return {
        "process_id": pid, "pset_version": "0", "mode": mode,
        "extent": {"unit": "rxn-mmol", "min": "0", "max": "1000000000000"},
        "ports": {"in": [{"port": "water", "accepts": ["h2o-l"]}],
                  "out": [{"port": "h2", "accepts": ["h2-g"]}, {"port": "o2", "accepts": ["o2-g"]}]},
        "stages": [{"stage_id": "split", "ops": [
            {"op": "REACT", "vector": {"h2-g": "2", "h2o-l": "-2", "o2-g": "1"}, "extent": {"kind": "ref", "name": "extent"}},
            {"op": "WORK", "a": R(1), "b": R(0)},
            *(ops_extra or []),
        ]}],
        "edges": [{"from": "port:water", "to": "stage:split"},
                  {"from": "stage:split", "to": "port:h2", "species": ["h2-g"]},
                  {"from": "stage:split", "to": "port:o2", "species": ["o2-g"]}],
        "failure_disposition": {"split": "RETAIN"},
        "restart_thresholds": thresholds or {},
        "constants": {},
    }


def combine_process(pid: str) -> dict:
    """2 H2 + O2 -> 2 H2O, the reverse: a material producer for V-03."""
    return {
        "process_id": pid, "pset_version": "0", "mode": "FLOW",
        "extent": {"unit": "rxn-mmol", "min": "0", "max": "1000000000000"},
        "ports": {"in": [{"port": "h2", "accepts": ["h2-g"]}, {"port": "o2", "accepts": ["o2-g"]}],
                  "out": [{"port": "water", "accepts": ["h2o-l"]}]},
        "stages": [{"stage_id": "join", "ops": [
            {"op": "REACT", "vector": {"h2-g": "-2", "h2o-l": "2", "o2-g": "-1"}, "extent": {"kind": "ref", "name": "extent"}},
            {"op": "WORK", "a": R(1), "b": R(0)},
        ]}],
        "edges": [{"from": "port:h2", "to": "stage:join"}, {"from": "port:o2", "to": "stage:join"},
                  {"from": "stage:join", "to": "port:water", "species": ["h2o-l"]}],
        "failure_disposition": {"join": "RETAIN"},
        "restart_thresholds": {},
        "constants": {},
    }


def machine(bid: str, processes: list[str], rated: dict, ports: list[tuple[str, str, str]], lanes: int = 1, condition=None) -> dict:
    return {
        "blueprint_id": bid, "capabilities": [], "processes": processes, "rated_work": rated, "lanes": str(lanes),
        "min_stable_rate": R(1, 10**12), "idle_power": {"amount": R(0), "unit": "w"},
        "ports": [{"port": p, "type": t, "direction": d} for p, t, d in ports],
        "condition_table": condition or [{"wear_at": "0", "capacity_factor": R(1)}], "embodied": {},
    }


SPLITTER_PORTS = [("water", "MATERIAL", "IN"), ("h2", "MATERIAL", "OUT"), ("o2", "MATERIAL", "OUT")]
JOINER_PORTS = [("h2", "MATERIAL", "IN"), ("o2", "MATERIAL", "IN"), ("water", "MATERIAL", "OUT")]


def tank(tid: str, capacity: int) -> dict:
    return {"template_id": tid, "accepts": ["h2o-l", "h2-g", "o2-g"], "capacity": {"amount": str(capacity), "unit": "mmol"}}


def kit(pid: str, kind: str, template: str) -> dict:
    return {"product_id": pid, "embodied": {}, "installs_as": {"kind": kind, "template": template}}


# ---------------------------------------------------------------- vector writer
class Vector:
    def __init__(self, vid: str, slug: str, title: str, refs: list[str], entries: dict[str, list[dict]], lots: list[dict], environment=()):
        self.dir = VECTORS / f"{vid}-{slug}"
        self.vid, self.title, self.refs = vid, title, refs
        self.entries, self.lots, self.environment = entries, lots, list(environment)
        self.commands: list[dict] = []
        self.script: list[dict] = []
        self.seq = 0

    def cmd(self, t: int, op: str, **args) -> str:
        self.seq += 1
        cid = f"cmd-{self.seq:04d}"
        args = {k: (str(v) if isinstance(v, int) else v) for k, v in args.items()}
        self.commands.append({"command_id": cid, "effective_us": str(t), "seq": str(self.seq), "op": op, "args": args})
        return cid

    def install(self, t: int, product: str, as_id: str) -> None:
        self.cmd(t, "INSTALL", lot_id="kits", product=product, location="pad-a", as_id=as_id)

    def feed(self, t: int, cid: str, frm: str, to: str) -> None:
        self.cmd(t, "CONNECT", connection_id=cid, template="pipe", from_port=frm, to_port=to)

    def job(self, t: int, jid: str, process: str, machine_id: str, extent: int, priority: int = 0, start: bool = True) -> None:
        self.cmd(t, "CREATE_JOB", job_id=jid, process=process, machine_id=machine_id, target_extent=extent, priority=priority)
        if start:
            self.cmd(t, "START", job_id=jid)

    def advance(self, t: int) -> None:
        self.script.append({"step": "advance_to", "t_us": str(t)})

    def snapshot(self, name: str) -> None:
        self.script.append({"step": "snapshot", "name": name})

    def restore(self, name: str) -> None:
        self.script.append({"step": "restore", "name": name})

    def save(self) -> None:
        if self.dir.exists():
            keep = self.dir / "expected"
            tmp = None
            if keep.exists():
                tmp = self.dir.parent / f".{self.dir.name}.expected"
                shutil.move(str(keep), tmp)
            shutil.rmtree(self.dir)
            self.dir.mkdir(parents=True)
            if tmp:
                shutil.move(str(tmp), self.dir / "expected")
        cat = self.dir / "catalog"
        dirs = {"elements": "elements", "units": "units", "substances": "substances", "processes": "processes", "machines": "machines",
                "products": "products", "buffers": "buffers", "connections": "connections", "environment": "environment"}
        for key, dirname in dirs.items():
            for item in self.entries.get(key, []):
                kind = [k for k, v in ld.CATALOG_KINDS.items() if v[2] == key][0]
                write(cat / dirname / f"{item[ld.CATALOG_KINDS[kind][1]]}.json", item)
        manifest = ld.manifest_for(f"vector-{self.vid[:4].lower()}", ld.read_catalog_entries(cat))
        write(cat / "manifest.json", manifest)
        write(self.dir / "genesis.json", {
            "schema": "ld.genesis.v0", "world_id": "vector-world", "claim_id": "claim-v", "catalog_hash": ld.catalog_hash(manifest),
            "start_us": "0", "deposits": [], "starting_lots": self.lots, "environment": self.environment})
        write(self.dir / "vector.json", {"id": self.vid, "title": self.title, "kind": "EXECUTION", "spec_refs": self.refs,
                                         "pset_version": "0", "numeric_profile": "provisional-u64-i128", "status": "DRAFT"})
        (self.dir / "commands.jsonl").write_text("".join(json.dumps(c) + "\n" for c in self.commands))
        (self.dir / "script.jsonl").write_text("".join(json.dumps(s) + "\n" for s in self.script))
        print(f"wrote {self.dir.relative_to(ld.ROOT)}: {len(self.commands)} commands, {len(self.script)} steps")


def lot(lot_id: str, location: str, composition=None, products=None) -> dict:
    return {"lot_id": lot_id, "location": location, "state": "AVAILABLE", "composition": composition or {}, "products": products or {}}


def splitter_plant(v: Vector, t: int, process: str, water: str = "water-tank") -> None:
    v.install(t, "splitter-kit", "splitter-1")
    v.install(t, "tank-kit", water)
    v.install(t, "tank-kit", "h2-tank")
    v.install(t, "tank-kit", "o2-tank")
    v.feed(t, "c-water", f"{water}.io", "splitter-1.water")
    v.feed(t, "c-h2", "splitter-1.h2", "h2-tank.io")
    v.feed(t, "c-o2", "splitter-1.o2", "o2-tank.io")


def v02() -> list[Vector]:
    out = []
    for suffix, title in [("a", "Batch job of 120 wu at 2 wu/us completes after 60 us"),
                          ("b", "Batch job at 1 wu/us for 40 us, then 2 wu/us, completes at 80 us")]:
        e = base_entries()
        e["processes"] = [split_process("split-batch", "BATCH")]
        e["machines"] = [machine("splitter", ["split-batch"], R(2), SPLITTER_PORTS)]
        e["buffers"] = [tank("tank", 1_000_000)]
        e["products"] = [kit("splitter-kit", "MACHINE", "splitter"), kit("tank-kit", "BUFFER", "tank")]
        v = Vector(f"V-02{suffix}", "work-completion", title, ["LD-PEC-001 §11 V-02", "LD-PEC-004 §5"], e,
                   [lot("kits", "inventory", products={"splitter-kit": "1", "tank-kit": "3"}), lot("water-1", "water-tank", {"h2o-l": "240"})])
        splitter_plant(v, 0, "split-batch")
        if suffix == "b":
            v.cmd(0, "SET_OPERATING_POLICY", machine_id="splitter-1", rate_setpoint=R(1))
        v.job(0, "job-batch", "split-batch", "splitter-1", 120)
        if suffix == "b":
            v.advance(40)
            v.cmd(40, "SET_OPERATING_POLICY", machine_id="splitter-1", rate_setpoint=R(2))
            v.advance(79)
            v.advance(80)
        else:
            v.advance(59)
            v.advance(60)
        v.advance(100)
        out.append(v)
    return out


def v03() -> list[Vector]:
    e = base_entries()
    # Producer: 30 units/h of 2 H2 + O2 -> 2 H2O, so 60 mmol/h of water into the buffer.
    # Consumer: 20 units/h of 2 H2O -> 2 H2 + O2, so 40 mmol/h out. Net +20 mmol/h.
    e["processes"] = [combine_process("join-flow"), split_process("split-flow", "FLOW")]
    e["machines"] = [machine("joiner", ["join-flow"], R(30, 3600 * S), JOINER_PORTS),
                     machine("splitter", ["split-flow"], R(20, 3600 * S), SPLITTER_PORTS)]
    e["buffers"] = [tank("tank", 10**9), tank("hopper", 100)]
    e["products"] = [kit("joiner-kit", "MACHINE", "joiner"), kit("splitter-kit", "MACHINE", "splitter"),
                     kit("tank-kit", "BUFFER", "tank"), kit("hopper-kit", "BUFFER", "hopper")]
    v = Vector("V-03", "finite-buffer", "A buffer filling at the net rate blocks its source when full and never overfills",
               ["LD-PEC-001 §11 V-03", "LD-PEC-004 §5"], e,
               [lot("kits", "inventory", products={"joiner-kit": "1", "splitter-kit": "1", "tank-kit": "4", "hopper-kit": "1"}),
                lot("h2-src", "h2-feed", {"h2-g": "1000000"}), lot("o2-src", "o2-feed", {"o2-g": "1000000"}), lot("w0", "buffer", {"h2o-l": "20"})])
    for kit_id, as_id in [("joiner-kit", "joiner-1"), ("splitter-kit", "splitter-1"), ("tank-kit", "h2-feed"), ("tank-kit", "o2-feed"),
                          ("hopper-kit", "buffer"), ("tank-kit", "h2-sink"), ("tank-kit", "o2-sink")]:
        v.install(0, kit_id, as_id)
    v.feed(0, "c-1", "h2-feed.io", "joiner-1.h2")
    v.feed(0, "c-2", "o2-feed.io", "joiner-1.o2")
    v.feed(0, "c-3", "joiner-1.water", "buffer.io")
    v.feed(0, "c-4", "buffer.io", "splitter-1.water")
    v.feed(0, "c-5", "splitter-1.h2", "h2-sink.io")
    v.feed(0, "c-6", "splitter-1.o2", "o2-sink.io")
    v.job(0, "job-make", "join-flow", "joiner-1", 10**9, priority=1)
    v.job(0, "job-use", "split-flow", "splitter-1", 10**9, priority=0)
    for hours in (1, 2, 3, 4, 5):
        v.advance(hours * H)
    return [v]


def v04() -> list[Vector]:
    out = []
    cases = [
        ("a", "Higher priority wins the lane", [("job-low", 1), ("job-high", 5)], 0),
        ("b", "At equal priority the earlier-created job wins", [("job-first", 3), ("job-second", 3)], 1),
        ("c", "At equal priority and time the smaller job id wins, whatever the creation order", [("job-b", 2), ("job-a", 2)], 0),
    ]
    for suffix, title, jobs, gap in cases:
        e = base_entries()
        e["processes"] = [split_process("split-flow", "FLOW")]
        e["machines"] = [machine("splitter", ["split-flow"], R(1, 1000), SPLITTER_PORTS)]
        e["buffers"] = [tank("tank", 1_000_000)]
        e["products"] = [kit("splitter-kit", "MACHINE", "splitter"), kit("tank-kit", "BUFFER", "tank")]
        v = Vector(f"V-04{suffix}", "competing-jobs", title, ["LD-PEC-001 §11 V-04", "LD-PEC-001 §5.1"], e,
                   [lot("kits", "inventory", products={"splitter-kit": "1", "tank-kit": "3"}), lot("water-1", "water-tank", {"h2o-l": "100000"})])
        splitter_plant(v, 0, "split-flow")
        t = 0
        for jid, prio in jobs:
            v.job(t, jid, "split-flow", "splitter-1", 10, priority=prio, start=False)
            t += gap
        for jid, _ in jobs:
            v.cmd(t, "START", job_id=jid)
        v.advance(t)
        v.advance(t + 100 * 1000)
        out.append(v)
    return out


def v05() -> list[Vector]:
    out = []
    for suffix, steps, title in [("a", 1, "One advance of 1 000 000 us"), ("b", 10, "Ten advances of 100 000 us reach the same state and history head")]:
        e = base_entries()
        # Rate 3/7 wu/us leaves fractional work and wear at every boundary.
        e["processes"] = [split_process("split-flow", "FLOW", [{"op": "WEAR", "per": "WORK", "amount": R(1, 3)}])]
        e["machines"] = [machine("splitter", ["split-flow"], R(3, 7), SPLITTER_PORTS)]
        e["machines"][0]["condition_table"] = [{"wear_at": "0", "capacity_factor": R(1)}, {"wear_at": "10000000", "capacity_factor": R(1, 2)}]
        e["buffers"] = [tank("tank", 10**9)]
        e["products"] = [kit("splitter-kit", "MACHINE", "splitter"), kit("tank-kit", "BUFFER", "tank")]
        v = Vector(f"V-05{suffix}", "subdivision", title, ["LD-PEC-001 §11 V-05", "LD-PEC-001 §6.1"], e,
                   [lot("kits", "inventory", products={"splitter-kit": "1", "tank-kit": "3"}), lot("water-1", "water-tank", {"h2o-l": "100000000"})])
        splitter_plant(v, 0, "split-flow")
        v.job(0, "job-flow", "split-flow", "splitter-1", 10**9)
        for i in range(1, steps + 1):
            v.advance(i * (1_000_000 // steps))
        out.append(v)
    return out


def v07() -> list[Vector]:
    e = base_entries()
    e["buffers"] = [tank("tank", 1_000_000)]
    e["products"] = [kit("tank-kit", "BUFFER", "tank")]
    v = Vector("V-07", "connection-delay", "A shipment is in transit for its loading time plus the 2 s delay, counted once",
               ["LD-PEC-001 §11 V-07", "LD-PEC-004 §7"], e,
               [lot("kits", "inventory", products={"tank-kit": "2"}), lot("water-1", "tank-a", {"h2o-l": "5000"})])
    v.install(0, "tank-kit", "tank-a")
    v.install(0, "tank-kit", "tank-b")
    v.cmd(0, "CONNECT", connection_id="c-belt", template="belt", from_port="tank-a.io", to_port="tank-b.io")
    v.advance(1_000_000)
    v.cmd(1_000_000, "TRANSFER_LOCAL", connection_id="c-belt", species="h2o-l", amount=1000)
    v.cmd(1_000_000, "TRANSFER_LOCAL", connection_id="c-belt", species="h2o-l", amount=500)
    v.advance(1_000_000 + 2_999_999)
    v.advance(1_000_000 + 3_000_000)
    v.advance(1_000_000 + 4_500_000)
    v.advance(10_000_000)
    return [v]


def v09() -> list[Vector]:
    e = base_entries()
    e["processes"] = [split_process("split-batch", "BATCH", [{"op": "DWELL", "duration_us": {"kind": "const", "value": R(500)}}])]
    e["machines"] = [machine("splitter", ["split-batch"], R(3, 7), SPLITTER_PORTS)]
    e["buffers"] = [tank("tank", 1_000_000)]
    e["products"] = [kit("splitter-kit", "MACHINE", "splitter"), kit("tank-kit", "BUFFER", "tank")]
    v = Vector("V-09", "mid-job-snapshot", "Restoring a mid-batch snapshot and advancing matches the uninterrupted run",
               ["LD-PEC-001 §11 V-09", "LD-PEC-004 §8"], e,
               [lot("kits", "inventory", products={"splitter-kit": "1", "tank-kit": "3"}), lot("water-1", "water-tank", {"h2o-l": "2000"})])
    splitter_plant(v, 0, "split-batch")
    v.job(0, "job-batch", "split-batch", "splitter-1", 1000)
    v.advance(1234)
    v.snapshot("mid")
    v.advance(5000)
    v.restore("mid")
    v.advance(5000)
    return [v]


def v10() -> list[Vector]:
    e = base_entries()
    e["processes"] = [split_process("split-batch", "BATCH"), split_process("split-flow", "FLOW")]
    e["machines"] = [machine("splitter", ["split-batch", "split-flow"], R(1), SPLITTER_PORTS)]
    e["buffers"] = [tank("tank", 1_000_000)]
    e["products"] = [kit("splitter-kit", "MACHINE", "splitter"), kit("tank-kit", "BUFFER", "tank")]
    e["connections"].append({"template_id": "chute", "kind": "CONVEYOR", "throughput": R(1), "unit": "mmol", "delay_us": "50"})
    # A step function that changes at exactly t = 100 us.
    e["environment"] = [{"function_id": "beacon", "unit": "w-m2", "period_us": "1000000",
                         "segments": [{"start_us": "0", "value": R(0)}, {"start_us": "100", "value": R(1)}]}]
    v = Vector("V-10", "same-timestamp", "Arrival, environment change, release and a command at one timestamp run in phase order",
               ["LD-PEC-001 \u00a711 V-10", "LD-PEC-001 \u00a76.2"], e,
               [lot("kits", "inventory", products={"splitter-kit": "1", "tank-kit": "4"}),
                lot("water-1", "water-tank", {"h2o-l": "200"}), lot("water-2", "reserve", {"h2o-l": "50"})],
               environment=["beacon"])
    splitter_plant(v, 0, "split-batch")
    v.install(0, "tank-kit", "reserve")
    v.cmd(0, "CONNECT", connection_id="c-chute", template="chute", from_port="reserve.io", to_port="water-tank.io")
    # 50 mmol load in 50 us and travel 50 us: the shipment arrives at t = 100.
    v.cmd(0, "TRANSFER_LOCAL", connection_id="c-chute", species="h2o-l", amount=50)
    # A batch of 100 at 1 wu/us finishes its work at t = 100 and releases then, freeing
    # the machine; the beacon changes at t = 100 too.
    v.job(0, "job-batch", "split-batch", "splitter-1", 100)
    v.advance(100)
    # At t = 100, after the phases: a job that uses the water that just arrived. It may
    # start at 100 but does no work until time passes.
    v.job(100, "job-next", "split-flow", "splitter-1", 10)
    v.advance(101)
    v.advance(200)
    return [v]


# ---------------------------------------------------------------- LD-PEC-004 amendment 1
WEARING = [{"wear_at": "0", "capacity_factor": R(1)}, {"wear_at": "100", "capacity_factor": R(1, 2)}, {"wear_at": "200", "capacity_factor": R(0)}]


def wearing_entries() -> dict[str, list[dict]]:
    e = base_entries()
    e["processes"] = [split_process("split-flow", "FLOW", [{"op": "WEAR", "per": "WORK", "amount": R(1, 1000)}])]
    e["machines"] = [machine("splitter", ["split-flow"], R(1, 1000), SPLITTER_PORTS, condition=WEARING)]
    e["buffers"] = [tank("tank", 10**9)]
    e["products"] = [kit("splitter-kit", "MACHINE", "splitter"), kit("tank-kit", "BUFFER", "tank")]
    return e


def unplug(v: Vector, t: int, machine_id: str = "splitter-1") -> None:
    for cid in ("c-water", "c-h2", "c-o2"):
        v.cmd(t, "DISCONNECT", connection_id=cid)
    v.cmd(t, "REMOVE", target_id=machine_id)


def v12() -> list[Vector]:
    v = Vector("V-12", "worn-kit", "A removed machine's kit carries its wear, and reinstalling resumes it",
               ["LD-PEC-004 A1-1"], wearing_entries(),
               [lot("kits", "inventory", products={"splitter-kit": "1", "tank-kit": "3"}), lot("water-1", "water-tank", {"h2o-l": "100000"})])
    splitter_plant(v, 0, "split-flow")
    v.job(0, "job-run", "split-flow", "splitter-1", 5000)  # 5 000 work at 1/1000 wear per work: wear 5
    v.advance(10 * S)
    unplug(v, 10 * S)
    v.cmd(10 * S, "INSTALL", lot_id="lot-1", product="splitter-kit", location="pad-a", as_id="splitter-2")
    v.advance(11 * S)
    return [v]


def v13() -> list[Vector]:
    v = Vector("V-13", "scrap", "A machine worn to zero capacity comes back as scrap, which INSTALL refuses",
               ["LD-PEC-004 A1-1"], wearing_entries(),
               [lot("kits", "inventory", products={"splitter-kit": "1", "tank-kit": "3"}), lot("water-1", "water-tank", {"h2o-l": "10000000"})])
    splitter_plant(v, 0, "split-flow")
    # Wear 100 after 100 s at full rate, then 100 more at half rate: fails at 300 s.
    v.job(0, "job-run", "split-flow", "splitter-1", 10**9)
    v.advance(400 * S)
    unplug(v, 400 * S)
    v.cmd(400 * S, "INSTALL", lot_id="lot-1", product="splitter-kit", location="pad-a", as_id="splitter-2")
    v.advance(401 * S)
    return [v]


def v14() -> list[Vector]:
    e = base_entries()
    e["processes"] = [split_process("split-flow", "FLOW")]
    e["machines"] = [machine("splitter", ["split-flow"], R(1, 1000), SPLITTER_PORTS)]
    e["buffers"] = [tank("tank", 10**9)]
    e["products"] = [kit("splitter-kit", "MACHINE", "splitter"), kit("tank-kit", "BUFFER", "tank")]
    # Each splitter needs 120 000 mmol of water per horizon; the tank holds 1 000 000.
    v = Vector("V-14", "shared-buffer", "Two flow jobs fed from one buffer both run, each reserving one horizon of need",
               ["LD-PEC-004 A1-2", "LD-PEC-004 §4.2"], e,
               [lot("kits", "inventory", products={"splitter-kit": "2", "tank-kit": "3"}), lot("water-1", "water-tank", {"h2o-l": "1000000"})])
    splitter_plant(v, 0, "split-flow")
    v.install(0, "splitter-kit", "splitter-2")
    v.feed(0, "c-water-2", "water-tank.io", "splitter-2.water")
    v.feed(0, "c-h2-2", "splitter-2.h2", "h2-tank.io")
    v.feed(0, "c-o2-2", "splitter-2.o2", "o2-tank.io")
    v.job(0, "job-first", "split-flow", "splitter-1", 10**9, priority=5)
    v.job(0, "job-second", "split-flow", "splitter-2", 10**9, priority=1)
    v.advance(30 * S)
    v.advance(90 * S)
    return [v]


def main() -> int:
    vectors = v02() + v03() + v04() + v05() + v07() + v09() + v10() + v12() + v13() + v14()
    for v in vectors:
        v.save()
    return 0


if __name__ == "__main__":
    sys.exit(main())
