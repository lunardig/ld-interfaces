"""M4a vectors (LD-PEC-004 Amendment 2, LD-PEC-008 §3.1): finished jobs leave the physical
state, a finished job holding material until its machine is removed, and a reactor that
carries its fuel in a core that travels with its kit. Every vector also exercises A2-2:
event-time history records carry no state hash.

    python tools/m4a_vectors.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from m1_vectors import R, S, Vector, base_entries, kit, lot, machine, splitter_plant, split_process, tank, SPLITTER_PORTS  # noqa: E402
from m2_vectors import bin_  # noqa: E402
from m2b_vectors import base, sorter  # noqa: E402
from m2c_vectors import DAY, power_entries, power_plant  # noqa: E402
from m3b_vectors import FRESH, SPENT, URANIUM, fission, fuel_substances  # noqa: E402
from m2_vectors import elements  # noqa: E402


def v28() -> list[Vector]:
    """A flow job completes and leaves the state at the event time it completes; its
    JOB_STATUS event is its last trace. A new job then reuses its id."""
    e = base_entries()
    e["processes"] = [split_process("split-flow", "FLOW")]
    e["machines"] = [machine("splitter", ["split-flow"], R(1, 1000), SPLITTER_PORTS)]
    e["buffers"] = [tank("tank", 10**9)]
    e["products"] = [kit("splitter-kit", "MACHINE", "splitter"), kit("tank-kit", "BUFFER", "tank")]
    v = Vector("V-28", "finished-jobs-leave", "A finished job leaves the physical state; its id may then be reused",
               ["LD-PEC-004 A2-1", "LD-PEC-004 A2-2"], e,
               [lot("kits", "inventory", products={"splitter-kit": "1", "tank-kit": "3"}), lot("water-1", "water-tank", {"h2o-l": "1000000"})])
    splitter_plant(v, 0, "split-flow")
    # 1 000 units at 1 wu/ms take 1 s.
    v.job(0, "job-a", "split-flow", "splitter-1", 1000)
    v.advance(2 * S)
    v.job(2 * S, "job-a", "split-flow", "splitter-1", 500)
    v.advance(3 * S)
    return [v]


def v29() -> list[Vector]:
    """A batch fails partway with RETAIN: its captured regolith stays with the failed job,
    which stays in the state. REMOVE of the machine moves that material to the cargo hold,
    and the job leaves."""
    e = base()
    batch = sorter()
    batch["process_id"] = "sort-batch"
    batch["mode"] = "BATCH"
    batch["stages"][0]["ops"].append({"op": "WEAR", "per": "WORK", "amount": R(1)})
    batch["failure_disposition"] = {"crush": "RETAIN", "sort": "RETAIN"}
    e["processes"] = [batch]
    e["machines"] = [machine("sorter", ["sort-batch"], R(1, S), [("feed", "MATERIAL", "IN"), ("ice", "MATERIAL", "OUT"), ("ilmenite", "MATERIAL", "OUT"),
                                                                ("tailings", "MATERIAL", "OUT")],
                             condition=[{"wear_at": "0", "capacity_factor": R(1)}, {"wear_at": "50", "capacity_factor": R(0)}])]
    e["buffers"] = [bin_("hopper", ["regolith"], 100_000, "kg-reg"), bin_("bin", ["h2o-s", "fetio3-s", "sio2-s"], 10**12, "mmol")]
    e["products"] = [kit("sorter-kit", "MACHINE", "sorter"), kit("hopper-kit", "BUFFER", "hopper"), kit("bin-kit", "BUFFER", "bin")]
    v = Vector("V-29", "retained-until-removed", "A failed batch keeps its material until its machine is removed; REMOVE moves it to the hold",
               ["LD-PEC-004 A2-1", "LD-PEC-003 §6 failure disposition"], e,
               [lot("kits", "inventory", products={"sorter-kit": "1", "hopper-kit": "1", "bin-kit": "3"}), lot("dug", "hopper-1", {"regolith": "100"})])
    for k, a in [("sorter-kit", "sorter-1"), ("hopper-kit", "hopper-1"), ("bin-kit", "ice-bin"), ("bin-kit", "ilmenite-bin"), ("bin-kit", "tailings")]:
        v.install(0, k, a)
    conns = [("c-feed", "hopper-1.io", "sorter-1.feed"), ("c-ice", "sorter-1.ice", "ice-bin.io"), ("c-ilm", "sorter-1.ilmenite", "ilmenite-bin.io"),
             ("c-tail", "sorter-1.tailings", "tailings.io")]
    for c, f, t in conns:
        v.feed(0, c, f, t)
    # 40 kg is 80 work at 1 wu/s; the machine fails at wear 50, after 50 s.
    v.job(0, "job-batch", "sort-batch", "sorter-1", 40)
    v.advance(60 * S)
    for c, _, _ in conns:
        v.cmd(60 * S, "DISCONNECT", connection_id=c)
    v.cmd(60 * S, "REMOVE", target_id="sorter-1")
    v.advance(61 * S)
    return [v]


def core_entries() -> dict:
    """V-27's plant with the reactor's fuel in a core: 10 kW, 2 kW minimum, following load."""
    e = power_entries()
    e["elements"] = elements() + [URANIUM]
    e["substances"] = e["substances"] + fuel_substances(1_000_000)
    e["processes"] = e["processes"] + [fission(250_000)]
    reactor = machine("reactor", ["fission"], R(1, 25_000_000), [("fuel", "MATERIAL", "IN"), ("spent", "MATERIAL", "OUT"), ("power", "ELECTRICAL", "OUT")])
    reactor["min_stable_rate"] = R(1, 125_000_000)
    reactor["core"] = {"buffer": "reactor-core", "connection": "core-link", "ports": ["fuel", "spent"]}
    e["machines"] = [m for m in e["machines"] if m["blueprint_id"] != "battery"] + [reactor]
    e["products"] = [p for p in e["products"] if p["product_id"] != "battery-kit"] + [kit("reactor-kit", "MACHINE", "reactor")]
    e["buffers"] = e["buffers"] + [bin_("reactor-core", [FRESH, SPENT], 10_000, "mmol")]
    # The core's links are internal: fast enough never to limit the reactor.
    e["connections"] = e["connections"] + [{"template_id": "core-link", "kind": "FEED", "throughput": R(1), "unit": "mmol", "delay_us": "0"}]
    return e


def v30() -> list[Vector]:
    """A reactor draws fuel from its core and returns spent fuel to it. The core and its
    links refuse connections, disconnection and removal on their own. REMOVE puts the
    core's fresh and spent fuel in the kit; reinstalling restores it."""
    e = core_entries()
    reactor_lot = dict(lot("reactor", "inventory", products={"reactor-kit": "1"}), core={FRESH: "1000"})
    v = Vector("V-30", "reactor-core", "A reactor carries its fuel in a core that travels with its kit",
               ["LD-PEC-004 A2-3", "LD-PEC-006 §3.7"], e,
               [lot("kits", "inventory", products={"solar-kit": "1", "melter-kit": "1", "tank-kit": "2"}), reactor_lot,
                lot("ice", "ice-tank", {"h2o-s": "1000000"})], environment=["irradiance"])
    for k, a in [("solar-kit", "solar-1"), ("melter-kit", "melter-1"), ("tank-kit", "ice-tank"), ("tank-kit", "water-tank")]:
        v.install(0, k, a)
    v.cmd(0, "INSTALL", lot_id="reactor", product="reactor-kit", location="pad-a", as_id="reactor-1")
    v.feed(0, "c-ice", "ice-tank.io", "melter-1.ice")
    v.feed(0, "c-water", "melter-1.water", "water-tank.io")
    # Refused: a pipe to a core-bound port, removing the core, cutting a core link.
    v.cmd(0, "CONNECT", connection_id="c-bad", template="pipe", from_port="ice-tank.io", to_port="reactor-1.fuel")
    v.cmd(0, "REMOVE", target_id="reactor-1-core")
    v.cmd(0, "DISCONNECT", connection_id="reactor-1-core-fuel")
    v.job(0, "job-sun", "generate-solar", "solar-1", 10**9, priority=100)
    v.job(0, "job-fission", "fission", "reactor-1", 10**9, priority=50)
    v.job(0, "job-melt", "melt-ice", "melter-1", 10**8, priority=10)
    for t in (50 * S, DAY, DAY + 50 * S):
        v.advance(t)
    t = DAY + 50 * S
    v.cmd(t, "CANCEL", job_id="job-fission")
    v.cmd(t, "REMOVE", target_id="reactor-1")
    v.cmd(t, "INSTALL", lot_id="lot-1", product="reactor-kit", location="pad-a", as_id="reactor-2")
    v.job(t, "job-fission-2", "fission", "reactor-2", 10**9, priority=50)
    v.advance(t + 50 * S)
    return [v]


def main() -> int:
    for v in v28() + v29() + v30():
        v.save()
    return 0


if __name__ == "__main__":
    sys.exit(main())
