"""Writes the M2b vectors (LD-PEC-005 §6): PARTITION and COMBINE in a stage graph,
setup work with startup energy, and SCRAP_TO_RESIDUE.

    python tools/m2b_vectors.py

Expected outputs come from an engine through ld-sdk's tools/run_vectors.py --write and
stay DRAFT until the reference evaluator reproduces them.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from m1_vectors import R, S, Vector, kit, lot, machine  # noqa: E402
from m2_vectors import (ICE, ILMENITE, IRRADIANCE, SILICATE, DepositVector, EXTENT, bin_, elements, energy, solar,  # noqa: E402,F401
                        substances, units)

REGOLITH = {"regolith": "-1", "h2o-s": str(ICE), "fetio3-s": str(ILMENITE), "sio2-s": str(SILICATE)}


def base() -> dict[str, list[dict]]:
    return {"elements": elements(), "units": units(), "substances": substances(), "processes": [], "machines": [], "products": [],
            "buffers": [], "connections": [{"template_id": "pipe", "kind": "FEED", "throughput": R(1000), "unit": "mmol", "delay_us": "0"}],
            "environment": []}


def sorter() -> dict:
    """Two stages: crush regolith into its constituents, then sort them imperfectly.

    The sort keeps 9/10 of the ice and 4/5 of the ilmenite, each with some silicate
    carried along; 1/10 of the silicate is fines. Fines and the residue combine into
    tailings. Shares are floored cumulatively over the job, and the residue's
    destination takes what they held back when the job completes (LD-PEC-005 §3.7)."""
    return {
        "process_id": "sort-regolith", "pset_version": "0", "mode": "FLOW",
        "extent": {"unit": "kg-reg", "min": "0", "max": "1000000000000"},
        "ports": {"in": [{"port": "feed", "accepts": ["regolith"]}],
                  "out": [{"port": "ice", "accepts": ["h2o-s", "sio2-s"]}, {"port": "ilmenite", "accepts": ["fetio3-s", "sio2-s"]},
                          {"port": "tailings", "accepts": ["h2o-s", "fetio3-s", "sio2-s"]}]},
        "stages": [
            {"stage_id": "crush", "ops": [
                {"op": "REACT", "vector": REGOLITH, "extent": EXTENT},
                {"op": "WORK", "a": R(1), "b": R(0)},
            ]},
            {"stage_id": "sort", "ops": [
                {"op": "PARTITION", "input": "sort", "residue": "coarse", "outputs": [
                    {"stream": "ice-rich", "fractions": {"h2o-s": R(9, 10), "sio2-s": R(1, 20)}},
                    {"stream": "concentrate", "fractions": {"fetio3-s": R(4, 5), "sio2-s": R(1, 20)}},
                    {"stream": "fines", "fractions": {"sio2-s": R(1, 10)}},
                ]},
                {"op": "COMBINE", "inputs": ["fines", "coarse"], "output": "waste"},
                {"op": "WORK", "a": R(1), "b": R(0)},
            ]},
        ],
        "edges": [
            {"from": "port:feed", "to": "stage:crush"},
            {"from": "stage:crush", "to": "stage:sort"},
            {"from": "stage:sort.ice-rich", "to": "port:ice"},
            {"from": "stage:sort.concentrate", "to": "port:ilmenite"},
            {"from": "stage:sort.waste", "to": "port:tailings"},
        ],
        "failure_disposition": {"crush": "RETAIN", "sort": "RETAIN"},
        "restart_thresholds": {},
        "constants": {},
    }


def v17() -> list[Vector]:
    e = base()
    e["processes"] = [sorter()]
    e["machines"] = [machine("sorter", ["sort-regolith"], R(1, S), [("feed", "MATERIAL", "IN"), ("ice", "MATERIAL", "OUT"),
                                                                   ("ilmenite", "MATERIAL", "OUT"), ("tailings", "MATERIAL", "OUT")])]
    e["buffers"] = [bin_("hopper", ["regolith"], 100_000, "kg-reg"), bin_("bin", ["h2o-s", "fetio3-s", "sio2-s"], 10**12, "mmol")]
    e["products"] = [kit("sorter-kit", "MACHINE", "sorter"), kit("hopper-kit", "BUFFER", "hopper"), kit("bin-kit", "BUFFER", "bin")]
    v = Vector("V-17", "stage-graph", "A two-stage sorter: PARTITION shares are cumulative floors, the residue takes the rest at completion; COMBINE merges streams",
               ["LD-PEC-003 §4 PARTITION, COMBINE", "LD-PEC-003 §6", "LD-PEC-005 §3.2", "LD-PEC-005 §3.7"], e,
               [lot("kits", "inventory", products={"sorter-kit": "1", "hopper-kit": "1", "bin-kit": "3"}), lot("dug", "hopper-1", {"regolith": "1000"})])
    for k, a in [("sorter-kit", "sorter-1"), ("hopper-kit", "hopper-1"), ("bin-kit", "ice-bin"), ("bin-kit", "ilmenite-bin"), ("bin-kit", "tailings")]:
        v.install(0, k, a)
    for c, f, t in [("c-feed", "hopper-1.io", "sorter-1.feed"), ("c-ice", "sorter-1.ice", "ice-bin.io"), ("c-ilm", "sorter-1.ilmenite", "ilmenite-bin.io"),
                    ("c-tail", "sorter-1.tailings", "tailings.io")]:
        v.feed(0, c, f, t)
    v.job(0, "job-sort", "sort-regolith", "sorter-1", 1000)
    v.advance(10 * S)
    v.advance(2000 * S)
    return [v]


def p02() -> list[Vector]:
    """LD-PEC-003 P-02, cumulative (LD-PEC-005 §3.7): 7 per unit into thirds over 1 000 units
    gives 2 333, 2 333 and 2 334 (the third is the residue)."""
    e = base()
    e["processes"] = [{
        "process_id": "melt-and-share", "pset_version": "0", "mode": "FLOW",
        "extent": {"unit": "mmol", "min": "0", "max": "1000000000000"},
        "ports": {"in": [{"port": "ice", "accepts": ["h2o-s"]}],
                  "out": [{"port": "a", "accepts": ["h2o-l"]}, {"port": "b", "accepts": ["h2o-l"]}, {"port": "c", "accepts": ["h2o-l"]}]},
        "stages": [{"stage_id": "share", "ops": [
            {"op": "PHASE", "from": "h2o-s", "to": "h2o-l", "quantity": {"kind": "op", "op": "mul", "args": [{"kind": "const", "value": R(7)}, EXTENT]}},
            {"op": "PARTITION", "input": "share", "residue": "third",
             "outputs": [{"stream": "first", "fractions": {"h2o-l": R(1, 3)}}, {"stream": "second", "fractions": {"h2o-l": R(1, 3)}}]},
            {"op": "WORK", "a": R(1), "b": R(0)},
            energy(50),
        ]}],
        "edges": [{"from": "port:ice", "to": "stage:share"}, {"from": "stage:share.first", "to": "port:a"},
                  {"from": "stage:share.second", "to": "port:b"}, {"from": "stage:share.third", "to": "port:c"}],
        "failure_disposition": {"share": "RETAIN"}, "restart_thresholds": {}, "constants": {},
    }, solar()]
    e["machines"] = [machine("sharer", ["melt-and-share"], R(1, 1000), [("ice", "MATERIAL", "IN"), ("a", "MATERIAL", "OUT"), ("b", "MATERIAL", "OUT"),
                                                                      ("c", "MATERIAL", "OUT"), ("power", "ELECTRICAL", "IN")]),
                     machine("solar-array", ["generate-solar"], R(1, S), [("power", "ELECTRICAL", "OUT")])]
    e["buffers"] = [bin_("tank", ["h2o-s", "h2o-l"], 10**9, "mmol")]
    e["products"] = [kit("sharer-kit", "MACHINE", "sharer"), kit("solar-kit", "MACHINE", "solar-array"), kit("tank-kit", "BUFFER", "tank")]
    e["environment"] = [IRRADIANCE]
    v = Vector("P-02", "partition-thirds", "PARTITION of 7 into thirds over 1 000 units: cumulative floors give 2 333 and 2 333, the residue 2 334",
               ["LD-PEC-003 §11 P-02", "LD-PEC-005 §3.7"], e,
               [lot("kits", "inventory", products={"sharer-kit": "1", "solar-kit": "1", "tank-kit": "4"}), lot("ice", "ice-tank", {"h2o-s": "7000"})],
               environment=["irradiance"])
    for k, a in [("solar-kit", "solar-1"), ("sharer-kit", "sharer-1"), ("tank-kit", "ice-tank"), ("tank-kit", "tank-a"), ("tank-kit", "tank-b"), ("tank-kit", "tank-c")]:
        v.install(0, k, a)
    for c, f, t in [("c-ice", "ice-tank.io", "sharer-1.ice"), ("c-a", "sharer-1.a", "tank-a.io"), ("c-b", "sharer-1.b", "tank-b.io"), ("c-c", "sharer-1.c", "tank-c.io")]:
        v.feed(0, c, f, t)
    v.job(0, "job-sun", "generate-solar", "solar-1", 10**9, priority=100)
    v.job(0, "job-share", "melt-and-share", "sharer-1", 1000, priority=10)
    v.advance(10 * S)
    return [v]


def v18() -> list[Vector]:
    """Setup work with startup energy: 10 000 work quanta of setup draw 2 MJ on top of the
    per-work draw, then units flow; the job reaches its target at a + b work."""
    e = base()
    e["processes"] = [{
        "process_id": "melt-ice", "pset_version": "0", "mode": "FLOW",
        "extent": {"unit": "mmol", "min": "0", "max": "1000000000000"},
        "ports": {"in": [{"port": "ice", "accepts": ["h2o-s"]}], "out": [{"port": "water", "accepts": ["h2o-l"]}]},
        "stages": [{"stage_id": "melt", "ops": [
            {"op": "PHASE", "from": "h2o-s", "to": "h2o-l", "quantity": EXTENT},
            {"op": "WORK", "a": R(1), "b": R(10_000)},
            energy(8),
            {"op": "ENERGY", "mode": "STARTUP", "dir": "DRAW", "amount": R(2_000_000), "unit": "j", "heat_sink": "waste-heat"},
        ]}],
        "edges": [{"from": "port:ice", "to": "stage:melt"}, {"from": "stage:melt", "to": "port:water", "species": ["h2o-l"]}],
        "failure_disposition": {"melt": "RETAIN"}, "restart_thresholds": {}, "constants": {},
    }, solar()]
    e["machines"] = [machine("melter", ["melt-ice"], R(1, 500), [("ice", "MATERIAL", "IN"), ("water", "MATERIAL", "OUT"), ("power", "ELECTRICAL", "IN")]),
                     machine("solar-array", ["generate-solar"], R(1, S), [("power", "ELECTRICAL", "OUT")])]
    e["buffers"] = [bin_("tank", ["h2o-s", "h2o-l"], 10**9, "mmol")]
    e["products"] = [kit("melter-kit", "MACHINE", "melter"), kit("solar-kit", "MACHINE", "solar-array"), kit("tank-kit", "BUFFER", "tank")]
    e["environment"] = [IRRADIANCE]
    v = Vector("V-18", "setup-and-startup", "Setup work runs first, drawing startup energy on top of the per-work draw; units flow only after it",
               ["LD-PEC-003 §5 WORK, ENERGY STARTUP", "LD-PEC-005 §3.8"], e,
               [lot("kits", "inventory", products={"melter-kit": "1", "solar-kit": "1", "tank-kit": "2"}), lot("ice", "ice-tank", {"h2o-s": "100000"})],
               environment=["irradiance"])
    for k, a in [("solar-kit", "solar-1"), ("melter-kit", "melter-1"), ("tank-kit", "ice-tank"), ("tank-kit", "water-tank")]:
        v.install(0, k, a)
    v.feed(0, "c-ice", "ice-tank.io", "melter-1.ice")
    v.feed(0, "c-water", "melter-1.water", "water-tank.io")
    v.job(0, "job-sun", "generate-solar", "solar-1", 10**9, priority=100)
    v.job(0, "job-melt", "melt-ice", "melter-1", 50_000, priority=10)
    for t in (1, 5, 6, 30, 60):
        v.advance(t * S)
    return [v]


def v19() -> list[Vector]:
    """A batch sorter fails partway; SCRAP_TO_RESIDUE sends its captured regolith to the
    tailings bin, where the residue stream goes."""
    e = base()
    batch = sorter()
    batch["process_id"] = "sort-batch"
    batch["mode"] = "BATCH"
    batch["stages"][0]["ops"].append({"op": "WEAR", "per": "WORK", "amount": R(1)})
    batch["failure_disposition"] = {"crush": "SCRAP_TO_RESIDUE", "sort": "RETAIN"}
    batch["ports"]["out"][2]["accepts"].append("regolith")
    e["processes"] = [batch]
    e["machines"] = [machine("sorter", ["sort-batch"], R(1, S), [("feed", "MATERIAL", "IN"), ("ice", "MATERIAL", "OUT"), ("ilmenite", "MATERIAL", "OUT"),
                                                                ("tailings", "MATERIAL", "OUT")],
                             condition=[{"wear_at": "0", "capacity_factor": R(1)}, {"wear_at": "50", "capacity_factor": R(0)}])]
    e["buffers"] = [bin_("hopper", ["regolith"], 100_000, "kg-reg"), bin_("bin", ["h2o-s", "fetio3-s", "sio2-s"], 10**12, "mmol"),
                    bin_("waste", ["regolith", "h2o-s", "fetio3-s", "sio2-s"], 10**9, "kg-reg")]
    e["products"] = [kit("sorter-kit", "MACHINE", "sorter"), kit("hopper-kit", "BUFFER", "hopper"), kit("bin-kit", "BUFFER", "bin"),
                     kit("waste-kit", "BUFFER", "waste")]
    v = Vector("V-19", "scrap-to-residue", "A failed batch with SCRAP_TO_RESIDUE sends its work in progress to the residue destination",
               ["LD-PEC-003 §6 failure disposition", "LD-PEC-005 §2 M2b"], e,
               [lot("kits", "inventory", products={"sorter-kit": "1", "hopper-kit": "1", "bin-kit": "2", "waste-kit": "1"}), lot("dug", "hopper-1", {"regolith": "100"})])
    for k, a in [("sorter-kit", "sorter-1"), ("hopper-kit", "hopper-1"), ("bin-kit", "ice-bin"), ("bin-kit", "ilmenite-bin"), ("waste-kit", "tailings")]:
        v.install(0, k, a)
    for c, f, t in [("c-feed", "hopper-1.io", "sorter-1.feed"), ("c-ice", "sorter-1.ice", "ice-bin.io"), ("c-ilm", "sorter-1.ilmenite", "ilmenite-bin.io"),
                    ("c-tail", "sorter-1.tailings", "tailings.io")]:
        v.feed(0, c, f, t)
    # 40 kg is 80 work at 1 wu/s; the machine fails at wear 50, after 50 s.
    v.job(0, "job-batch", "sort-batch", "sorter-1", 40)
    v.advance(60 * S)
    return [v]


def screen_entries() -> dict[str, list[dict]]:
    """A screen: a stage that only splits. Its PARTITION draws 1 kg of regolith per unit
    from the feed and sends 3/10 to fines; the coarse residue takes the rest (§3.8)."""
    e = base()
    e["processes"] = [{
        "process_id": "screen", "pset_version": "0", "mode": "FLOW",
        "extent": {"unit": "kg-reg", "min": "0", "max": "1000000000000"},
        "ports": {"in": [{"port": "feed", "accepts": ["regolith"]}],
                  "out": [{"port": "fines", "accepts": ["regolith"]}, {"port": "coarse", "accepts": ["regolith"]}]},
        "stages": [{"stage_id": "screen", "ops": [
            {"op": "PARTITION", "input": "feed", "draw": {"regolith": EXTENT}, "residue": "oversize",
             "outputs": [{"stream": "undersize", "fractions": {"regolith": R(3, 10)}}]},
            {"op": "WORK", "a": R(1), "b": R(0)},
        ]}],
        "edges": [{"from": "stage:screen.undersize", "to": "port:fines"}, {"from": "stage:screen.oversize", "to": "port:coarse"}],
        "failure_disposition": {"screen": "RETAIN"}, "restart_thresholds": {}, "constants": {},
    }]
    e["machines"] = [machine("screen", ["screen"], R(1, S), [("feed", "MATERIAL", "IN"), ("fines", "MATERIAL", "OUT"), ("coarse", "MATERIAL", "OUT")])]
    e["buffers"] = [bin_("hopper", ["regolith"], 100_000, "kg-reg")]
    e["products"] = [kit("screen-kit", "MACHINE", "screen"), kit("hopper-kit", "BUFFER", "hopper")]
    return e


def screen_setup(v: Vector) -> None:
    for k, a in [("screen-kit", "screen-1"), ("hopper-kit", "hopper-1"), ("hopper-kit", "fines-bin"), ("hopper-kit", "coarse-bin")]:
        v.install(0, k, a)
    for c, f, t in [("c-feed", "hopper-1.io", "screen-1.feed"), ("c-fines", "screen-1.fines", "fines-bin.io"), ("c-coarse", "screen-1.coarse", "coarse-bin.io")]:
        v.feed(0, c, f, t)
    v.job(0, "job-screen", "screen", "screen-1", 100)


def screen_lots() -> list[dict]:
    return [lot("kits", "inventory", products={"screen-kit": "1", "hopper-kit": "3"}), lot("dug", "hopper-1", {"regolith": "1000"})]


def v20() -> list[Vector]:
    """A bare screen runs to completion: 30 and 70 kg of 100. Midway, after 5 kg, the
    fines bin holds 1 kg, coarse 3 kg and the machine 1 kg, held back by the floors; the
    held lot survives a snapshot and restore."""
    v = Vector("V-20", "bare-screen", "A stage that only splits: PARTITION draws its own material per unit; cumulative floors hold back under one quantum each until completion",
               ["LD-PEC-003 §4 PARTITION", "LD-PEC-005 §3.7", "LD-PEC-005 §3.8"], screen_entries(), screen_lots())
    screen_setup(v)
    v.advance(5 * S)
    v.snapshot("mid")
    v.advance(50 * S)
    v.restore("mid")
    v.advance(200 * S)
    return [v]


def v21() -> list[Vector]:
    """Cancelled after 5 kg: what the floors held back goes to the residue's bin, so the
    fines bin keeps 1 kg and the coarse bin gets 4 kg."""
    v = Vector("V-21", "cancel-releases-holdup", "A cancelled FLOW job sends the material its cumulative floors held back to the residue's destination",
               ["LD-PEC-005 §3.7"], screen_entries(), screen_lots())
    screen_setup(v)
    v.cmd(5_500_000, "CANCEL", job_id="job-screen")
    v.advance(5 * S)
    v.advance(20 * S)
    return [v]


def main() -> int:
    for v in p02() + v17() + v18() + v19() + v20() + v21():
        v.save()
    return 0


if __name__ == "__main__":
    sys.exit(main())
