"""M3a process builders and vectors (LD-PEC-006 §3.3): beneficiation as a PARTITION
sorter with recovery fractions, and ilmenite reduction with partial conversion and a
magnetic separation stage. ld-sdk's alpha catalog imports the builders.

    python tools/m3a_vectors.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from m1_vectors import R, S, Vector, kit, lot, machine  # noqa: E402
from m2_vectors import EXTENT, ICE, ILMENITE, IRRADIANCE, SILICATE, bin_, elements, energy, solar, units  # noqa: E402
from m2c_vectors import IRON, RUTILE, m2c_substances  # noqa: E402

# Recoveries and conversion after domain review (LD-PEC-006 §2.4, Q-06b): the sorter keeps
# 65 % of the ice and 50 % of the ilmenite; the reactor reacts half the ilmenite it is fed
# per pass; the magnetic stage recovers 85 % of the iron.
ICE_RECOVERY, ILMENITE_RECOVERY, CONVERSION, IRON_RECOVERY = R(13, 20), R(1, 2), R(1, 2), R(17, 20)


def alpha_beneficiate() -> dict:
    """One kilogram of regolith into its constituents, then sorted (LD-PEC-006 §3.3):
    what the sorter does not recover goes to the tailings pile, still material."""
    stage = "beneficiate"
    return {
        "process_id": "beneficiate", "pset_version": "0", "mode": "FLOW",
        "extent": {"unit": "kg-reg", "min": "0", "max": "1000000000000"},
        "ports": {"in": [{"port": "feed", "accepts": ["regolith"]}],
                  "out": [{"port": "ice", "accepts": ["h2o-s"]}, {"port": "ilmenite", "accepts": ["fetio3-s"]},
                          {"port": "tailings", "accepts": ["sio2-s", "h2o-s", "fetio3-s"]}]},
        "stages": [{"stage_id": stage, "ops": [
            {"op": "REACT", "vector": {"regolith": "-1", "h2o-s": str(ICE), "fetio3-s": str(ILMENITE), "sio2-s": str(SILICATE)},
             "extent": EXTENT},
            {"op": "PARTITION", "input": "pool", "residue": "rest", "outputs": [
                {"stream": "icy", "fractions": {"h2o-s": ICE_RECOVERY}}, {"stream": "concentrate", "fractions": {"fetio3-s": ILMENITE_RECOVERY}}]},
            {"op": "WORK", "a": R(1), "b": R(0)},
            energy(20_000),
        ]}],
        "edges": [{"from": "port:feed", "to": f"stage:{stage}"}, {"from": f"stage:{stage}.icy", "to": "port:ice"},
                  {"from": f"stage:{stage}.concentrate", "to": "port:ilmenite"}, {"from": f"stage:{stage}.rest", "to": "port:tailings"}],
        "failure_disposition": {stage: "RETAIN"}, "restart_thresholds": {"feed": {"restart_at": "50", "unit": "kg-reg"}}, "constants": {},
    }


def alpha_reduce() -> dict:
    """Ilmenite reduction with partial conversion and magnetic separation (LD-PEC-006
    §3.3). Per unit (one mole of reaction, in mmol): 2 mmol of ilmenite are fed and half
    react; the unreacted half leaves by its own port, to go back to the ilmenite bin.
    The magnetic stage sends 85 % of the iron to the iron port; the rest leaves with
    the rutile. 250 J per mmol of ilmenite fed; a 10-minute batch dwell."""
    feed = {"kind": "op", "op": "mul", "args": [{"kind": "const", "value": R(2)}, EXTENT]}
    return {
        "process_id": "reduce-ilmenite", "pset_version": "0", "mode": "BATCH",
        "extent": {"unit": "rxn-mmol", "min": "1", "max": "1000000000"},
        "ports": {"in": [{"port": "ilmenite", "accepts": ["fetio3-s"]}, {"port": "h2", "accepts": ["h2-g"]}],
                  "out": [{"port": "iron", "accepts": [IRON]}, {"port": "rutile", "accepts": [RUTILE, IRON]},
                          {"port": "water", "accepts": ["h2o-l"]}, {"port": "unreacted", "accepts": ["fetio3-s"]}]},
        "stages": [
            {"stage_id": "charge", "ops": [
                {"op": "PARTITION", "input": "ilmenite", "draw": {"fetio3-s": feed}, "residue": "unreacted",
                 "outputs": [{"stream": "reacting", "fractions": {"fetio3-s": CONVERSION}}]},
            ]},
            {"stage_id": "reduce", "ops": [
                {"op": "REACT", "vector": {"fetio3-s": "-1", "h2-g": "-1", IRON: "1", RUTILE: "1", "h2o-l": "1"}, "extent": EXTENT},
                {"op": "PARTITION", "input": "pool", "residue": "nonmagnetic", "outputs": [
                    {"stream": "magnetic", "fractions": {IRON: IRON_RECOVERY}}, {"stream": "steam", "fractions": {"h2o-l": R(1)}}]},
                {"op": "WORK", "a": R(1), "b": R(0)},
                {"op": "ENERGY", "mode": "PER_WORK", "dir": "DRAW", "amount": R(500), "unit": "j", "heat_sink": "waste-heat"},
                {"op": "DWELL", "duration_us": {"kind": "const", "value": R(600_000_000)}},
            ]},
        ],
        "edges": [{"from": "stage:charge.reacting", "to": "stage:reduce"}, {"from": "stage:charge.unreacted", "to": "port:unreacted"},
                  {"from": "port:h2", "to": "stage:reduce"}, {"from": "stage:reduce.magnetic", "to": "port:iron"},
                  {"from": "stage:reduce.steam", "to": "port:water"}, {"from": "stage:reduce.nonmagnetic", "to": "port:rutile"}],
        "failure_disposition": {"charge": "RETAIN", "reduce": "RETAIN"}, "restart_thresholds": {}, "constants": {},
    }


def v24() -> list[Vector]:
    """A 100 mol reduction batch: 200 mol of ilmenite fed, half reacted. 85 mol of iron
    reach the iron bin; 15 mol leave with 100 mol of rutile; 100 mol of ilmenite come
    back unreacted; 100 mol of water."""
    e = {"elements": elements(), "units": units(), "substances": m2c_substances(), "processes": [alpha_reduce(), solar()],
         "machines": [machine("reactor", ["reduce-ilmenite"], R(1, 2000), [("ilmenite", "MATERIAL", "IN"), ("h2", "MATERIAL", "IN"), ("iron", "MATERIAL", "OUT"),
                                                                         ("rutile", "MATERIAL", "OUT"), ("water", "MATERIAL", "OUT"), ("unreacted", "MATERIAL", "OUT"),
                                                                         ("power", "ELECTRICAL", "IN")]),
                      machine("solar-array", ["generate-solar"], R(1, S), [("power", "ELECTRICAL", "OUT")])],
         "products": [kit("solar-kit", "MACHINE", "solar-array"), kit("reactor-kit", "MACHINE", "reactor"), kit("bin-kit", "BUFFER", "bin")],
         "buffers": [bin_("bin", ["fetio3-s", "h2-g", IRON, RUTILE, "h2o-l"], 10**9, "mmol")],
         "connections": [{"template_id": "pipe", "kind": "FEED", "throughput": R(1, 100), "unit": "mmol", "delay_us": "0"}], "environment": [IRRADIANCE]}
    v = Vector("V-24", "partial-reduction", "Reduction with partial conversion and magnetic separation conserves every element; unreacted ilmenite returns",
               ["LD-PEC-006 §3.3", "LD-PEC-005 §3.7"], e,
               [lot("kits", "inventory", products={"solar-kit": "1", "reactor-kit": "1", "bin-kit": "6"}), lot("ilm", "ilmenite-bin", {"fetio3-s": "300000"}),
                lot("h2", "h2-bin", {"h2-g": "300000"})], environment=["irradiance"])
    v.install(0, "solar-kit", "solar-1")
    v.job(0, "job-sun", "generate-solar", "solar-1", 10**9, priority=100)
    v.install(0, "reactor-kit", "reactor-1")
    for b in ["ilmenite-bin", "h2-bin", "iron-bin", "rutile-bin", "water-bin", "return-bin"]:
        v.install(0, "bin-kit", b)
    for c, f, t in [("c-i", "ilmenite-bin.io", "reactor-1.ilmenite"), ("c-h", "h2-bin.io", "reactor-1.h2"), ("c-fe", "reactor-1.iron", "iron-bin.io"),
                    ("c-ti", "reactor-1.rutile", "rutile-bin.io"), ("c-w", "reactor-1.water", "water-bin.io"), ("c-u", "reactor-1.unreacted", "return-bin.io")]:
        v.feed(0, c, f, t)
    v.job(0, "job-reduce", "reduce-ilmenite", "reactor-1", 100_000)
    v.advance(100 * S)
    v.advance(900 * S)
    return [v]


def v25() -> list[Vector]:
    """The PARTITION sorter: 1 000 kg of regolith. 65 % of the ice and 50 % of the
    ilmenite are recovered; everything else, silicate included, is on the tailings pile."""
    e = {"elements": elements(), "units": units(), "substances": m2c_substances(), "processes": [alpha_beneficiate(), solar()],
         "machines": [machine("sorter", ["beneficiate"], R(1, S), [("feed", "MATERIAL", "IN"), ("ice", "MATERIAL", "OUT"), ("ilmenite", "MATERIAL", "OUT"),
                                                                 ("tailings", "MATERIAL", "OUT"), ("power", "ELECTRICAL", "IN")]),
                      machine("solar-array", ["generate-solar"], R(1, S), [("power", "ELECTRICAL", "OUT")])],
         "products": [kit("solar-kit", "MACHINE", "solar-array"), kit("sorter-kit", "MACHINE", "sorter"), kit("hopper-kit", "BUFFER", "hopper"), kit("bin-kit", "BUFFER", "bin")],
         "buffers": [bin_("hopper", ["regolith"], 100_000, "kg-reg"), bin_("bin", ["h2o-s", "fetio3-s", "sio2-s"], 10**11, "mmol")],
         "connections": [{"template_id": "pipe", "kind": "FEED", "throughput": R(1, 100), "unit": "mmol", "delay_us": "0"}], "environment": [IRRADIANCE]}
    v = Vector("V-25", "recovery-sorter", "Beneficiation as a PARTITION sorter: recovered fractions to bins, the rest to tailings, all conserved",
               ["LD-PEC-006 §3.3"], e,
               [lot("kits", "inventory", products={"solar-kit": "1", "sorter-kit": "1", "hopper-kit": "1", "bin-kit": "3"}), lot("dug", "hopper-1", {"regolith": "1000"})],
               environment=["irradiance"])
    v.install(0, "solar-kit", "solar-1")
    v.job(0, "job-sun", "generate-solar", "solar-1", 10**9, priority=100)
    for k, a in [("sorter-kit", "sorter-1"), ("hopper-kit", "hopper-1"), ("bin-kit", "ice-bin"), ("bin-kit", "ilmenite-bin"), ("bin-kit", "tailings-pile")]:
        v.install(0, k, a)
    for c, f, t in [("c-f", "hopper-1.io", "sorter-1.feed"), ("c-i", "sorter-1.ice", "ice-bin.io"), ("c-m", "sorter-1.ilmenite", "ilmenite-bin.io"),
                    ("c-t", "sorter-1.tailings", "tailings-pile.io")]:
        v.feed(0, c, f, t)
    v.job(0, "job-sort", "beneficiate", "sorter-1", 1000)
    v.advance(500 * S)
    v.advance(2000 * S)
    return [v]


def main() -> int:
    for v in v24() + v25():
        v.save()
    return 0


if __name__ == "__main__":
    sys.exit(main())
