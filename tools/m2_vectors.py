"""Writes the M2a vectors (LD-PEC-005 §6): PHASE, LOSS and energy admission, and the
mining chain from a deposit to hydrogen.

    python tools/m2_vectors.py

Execution vectors get expected/ from an engine through ld-sdk's tools/run_vectors.py
--write. Admission vectors carry their expected verdict here. All stay DRAFT until the
reference evaluator reproduces them.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ld  # noqa: E402
from m1_vectors import R, S, Vector, kit, lot, machine, write  # noqa: E402

# ---------------------------------------------------------------- the M2a chemistry
# One kilogram of icy regolith, in millimoles of each element (LD-PEC-005 §3.4):
# 5 % ice (2 775 mmol H2O), 10 % ilmenite (659 mmol FeTiO3), 85 % silicate (14 148 mmol SiO2).
ICE, ILMENITE, SILICATE = 2775, 659, 14148
REGOLITH_FORMULA = {"h": str(2 * ICE), "o": str(ICE + 3 * ILMENITE + 2 * SILICATE), "si": str(SILICATE), "fe": str(ILMENITE), "ti": str(ILMENITE)}


def elements() -> list[dict]:
    return [
        {"element_id": "h", "symbol": "H", "molar_mass": R(1008, 1000)},
        {"element_id": "o", "symbol": "O", "molar_mass": R(15999, 1000)},
        {"element_id": "si", "symbol": "Si", "molar_mass": R(28085, 1000)},
        {"element_id": "fe", "symbol": "Fe", "molar_mass": R(55845, 1000)},
        {"element_id": "ti", "symbol": "Ti", "molar_mass": R(47867, 1000)},
    ]


def units() -> list[dict]:
    return [
        {"unit_id": "mmol", "dimension": "amount", "scale": R(1, 1000)},
        {"unit_id": "rxn-mmol", "dimension": "amount", "scale": R(1, 1000)},
        # One kilogram of regolith: one millimole of its formula unit (LD-PEC-005 §3.4).
        {"unit_id": "kg-reg", "dimension": "amount", "scale": R(1, 1000)},
        {"unit_id": "wu", "dimension": "work", "scale": R(1)},
        {"unit_id": "j", "dimension": "energy", "scale": R(1)},
        {"unit_id": "w", "dimension": "power", "scale": R(1)},
        {"unit_id": "w-m2", "dimension": "power", "scale": R(1)},
        {"unit_id": "s", "dimension": "time", "scale": R(1)},
    ]


# Standard enthalpies and Gibbs energies of formation at 298.15 K, in J per mmol (= kJ/mol),
# one dataset per species (Q-13c, LD-PEC-006 §2.4): ilmenite, rutile and quartz from Robie &
# Hemingway (1995, USGS Bulletin 2131); liquid water from CODATA/NIST-JANAF; ice at 298 K
# (metastable) from Argonne ATcT. Regolith's energy is the sum of its constituents', so
# beneficiation neither absorbs nor releases energy.
H = {"h2o-l": (-285830, 1000), "h2o-s": (-292713, 1000), "h2-g": (0, 1), "o2-g": (0, 1), "fetio3-s": (-12320, 10), "sio2-s": (-9107, 10),
     "fe-s": (0, 1), "tio2-s": (-9440, 10)}
G = {"h2o-l": (-237141, 1000), "h2-g": (0, 1), "o2-g": (0, 1), "fe-s": (0, 1), "tio2-s": (-8888, 10), "sio2-s": (-8563, 10),
     "fetio3-s": (-11555, 10)}


def regolith_enthalpy() -> dict:
    from fractions import Fraction as F
    h = F(*H["h2o-s"]) * ICE + F(*H["fetio3-s"]) * ILMENITE + F(*H["sio2-s"]) * SILICATE
    return R(h.numerator, h.denominator)


def with_energy(subs: list[dict]) -> list[dict]:
    """Adds enthalpy and Gibbs energy (LD-PEC-006 §3.2.1) to the substances that have them."""
    out = []
    for x in subs:
        x = dict(x)
        sid = x["substance_id"]
        if sid in H:
            x["enthalpy"] = R(*H[sid])
        if sid in G:
            x["gibbs"] = R(*G[sid])
        if sid in ("regolith", "regolith-bank"):
            x["enthalpy"] = regolith_enthalpy()
        out.append(x)
    return out


def substances() -> list[dict]:
    return with_energy(substances_plain())


def substances_plain() -> list[dict]:
    return [
        {"substance_id": "regolith-bank", "formula": REGOLITH_FORMULA, "phase": "solid", "quantity_unit": "kg-reg"},
        {"substance_id": "regolith", "formula": REGOLITH_FORMULA, "phase": "solid", "quantity_unit": "kg-reg"},
        {"substance_id": "h2o-s", "formula": {"h": "2", "o": "1"}, "phase": "solid", "quantity_unit": "mmol", "latent_to": {"h2o-l": R(601, 100)}},
        {"substance_id": "h2o-l", "formula": {"h": "2", "o": "1"}, "phase": "liquid", "quantity_unit": "mmol"},
        {"substance_id": "h2-g", "formula": {"h": "2"}, "phase": "gas", "quantity_unit": "mmol"},
        {"substance_id": "o2-g", "formula": {"o": "2"}, "phase": "gas", "quantity_unit": "mmol"},
        {"substance_id": "fetio3-s", "formula": {"fe": "1", "ti": "1", "o": "3"}, "phase": "solid", "quantity_unit": "mmol"},
        {"substance_id": "sio2-s", "formula": {"si": "1", "o": "2"}, "phase": "solid", "quantity_unit": "mmol"},
    ]


def proc(pid: str, inputs: list[tuple[str, list[str]]], outputs: list[tuple[str, list[str]]], ops: list[dict], unit: str = "rxn-mmol",
         thresholds: dict | None = None) -> dict:
    stage = pid
    return {
        "process_id": pid, "pset_version": "0", "mode": "FLOW",
        "extent": {"unit": unit, "min": "0", "max": "1000000000000"},
        "ports": {"in": [{"port": p, "accepts": a} for p, a in inputs], "out": [{"port": p, "accepts": a} for p, a in outputs]},
        "stages": [{"stage_id": stage, "ops": ops}],
        "edges": [{"from": f"port:{p}", "to": f"stage:{stage}"} for p, _ in inputs]
        + [{"from": f"stage:{stage}", "to": f"port:{p}", "species": a} for p, a in outputs],
        "failure_disposition": {stage: "RETAIN"},
        "restart_thresholds": thresholds or {},
        "constants": {},
    }


EXTENT = {"kind": "ref", "name": "extent"}


def times(n: int) -> dict:
    return {"kind": "op", "op": "mul", "args": [{"kind": "const", "value": R(n)}, EXTENT]}


def energy(j_per_work: int) -> dict:
    return {"op": "ENERGY", "mode": "PER_WORK", "dir": "DRAW", "amount": R(j_per_work), "unit": "j", "heat_sink": "waste-heat"}


def excavate() -> dict:
    """100 kg of regolith in place per unit; 99 kg come out, 1 kg is lost as dust."""
    return proc("excavate", [("face", ["regolith-bank"])], [("out", ["regolith"])], [
        {"op": "REACT", "vector": {"regolith-bank": "-100", "regolith": "100"}, "extent": EXTENT},
        {"op": "LOSS", "species": "regolith", "quantity": EXTENT, "sink": "dust", "sink_kind": "TERMINAL"},
        {"op": "WORK", "a": R(1), "b": R(0)},
        energy(50_000),
        {"op": "WEAR", "per": "WORK", "amount": R(1, 1000)},
    ], unit="kg-reg")


def beneficiate() -> dict:
    """One kilogram of regolith into its ice and ilmenite; the silicate goes to tailings."""
    return proc("beneficiate", [("feed", ["regolith"])], [("ice", ["h2o-s"]), ("ilmenite", ["fetio3-s"])], [
        {"op": "REACT", "vector": {"regolith": "-1", "h2o-s": str(ICE), "fetio3-s": str(ILMENITE), "sio2-s": str(SILICATE)}, "extent": EXTENT},
        {"op": "LOSS", "species": "sio2-s", "quantity": times(SILICATE), "sink": "tailings", "sink_kind": "RECOVERABLE"},
        {"op": "WORK", "a": R(1), "b": R(0)},
        energy(20_000),
    ], unit="kg-reg", thresholds={"feed": {"restart_at": "50", "unit": "kg-reg"}})


def melt(j_per_mmol: int = 8) -> dict:
    """Ice to water: 6.01 J/mmol latent, drawn as 8 J/mmol."""
    return proc("melt-ice", [("ice", ["h2o-s"])], [("water", ["h2o-l"])], [
        {"op": "PHASE", "from": "h2o-s", "to": "h2o-l", "quantity": EXTENT},
        {"op": "WORK", "a": R(1), "b": R(0)},
        energy(j_per_mmol),
    ], unit="mmol", thresholds={"ice": {"restart_at": "20000", "unit": "mmol"}})


def electrolyze() -> dict:
    return proc("electrolyze-water", [("water", ["h2o-l"])], [("h2", ["h2-g"]), ("o2", ["o2-g"])], [
        {"op": "REACT", "vector": {"h2-g": "2", "h2o-l": "-2", "o2-g": "1"}, "extent": EXTENT},
        {"op": "WORK", "a": R(1), "b": R(0)},
        energy(572),
    ], thresholds={"water": {"restart_at": "5000", "unit": "mmol"}})


def solar() -> dict:
    return {
        "process_id": "generate-solar", "pset_version": "0", "mode": "FLOW",
        "extent": {"unit": "s", "min": "0", "max": "1000000000000"},
        "ports": {"in": [], "out": []},
        "stages": [{"stage_id": "generate", "ops": [
            {"op": "REQUIRE", "predicate": {"kind": "environment", "function_id": "irradiance", "min": R(100), "max": R(2000)}},
            {"op": "WORK", "a": R(1), "b": R(0)},
            {"op": "ENERGY", "mode": "PER_WORK", "dir": "PRODUCE", "amount": R(1_000_000), "unit": "j", "heat_sink": "waste-heat"},
        ]}],
        "edges": [], "failure_disposition": {"generate": "RETAIN"}, "restart_thresholds": {}, "constants": {},
    }


IRRADIANCE = {"function_id": "irradiance", "unit": "w-m2", "period_us": "2551442877000",
              "segments": [{"start_us": "0", "value": R(1361)}, {"start_us": "1275721438500", "value": R(0)}]}


def bin_(tid: str, accepts: list[str], amount: int, unit: str) -> dict:
    return {"template_id": tid, "accepts": accepts, "capacity": {"amount": str(amount), "unit": unit}}


def chain_entries() -> dict[str, list[dict]]:
    return {
        "elements": elements(),
        "units": units(),
        "substances": substances(),
        "processes": [excavate(), beneficiate(), melt(), electrolyze(), solar()],
        "machines": [
            machine("excavator", ["excavate"], R(1, 60 * S), [("face", "MATERIAL", "IN"), ("out", "MATERIAL", "OUT"), ("power", "ELECTRICAL", "IN")],
                    condition=[{"wear_at": "0", "capacity_factor": R(1)}, {"wear_at": "1000000", "capacity_factor": R(1, 2)}]),
            machine("beneficiator", ["beneficiate"], R(2, S), [("feed", "MATERIAL", "IN"), ("ice", "MATERIAL", "OUT"), ("ilmenite", "MATERIAL", "OUT"),
                                                              ("power", "ELECTRICAL", "IN")]),
            machine("melter", ["melt-ice"], R(1, 500), [("ice", "MATERIAL", "IN"), ("water", "MATERIAL", "OUT"), ("power", "ELECTRICAL", "IN")]),
            machine("electrolyzer", ["electrolyze-water"], R(1, 1000), [("water", "MATERIAL", "IN"), ("h2", "MATERIAL", "OUT"), ("o2", "MATERIAL", "OUT"),
                                                                       ("power", "ELECTRICAL", "IN")]),
            machine("solar-array", ["generate-solar"], R(1, S), [("power", "ELECTRICAL", "OUT")]),
        ],
        "products": [kit(f"{m}-kit", "MACHINE", m) for m in ["excavator", "beneficiator", "melter", "electrolyzer", "solar-array"]]
        + [kit(f"{b}-kit", "BUFFER", b) for b in ["hopper", "ice-bin", "ilmenite-bin", "tank"]],
        "buffers": [
            bin_("hopper", ["regolith"], 5000, "kg-reg"),
            bin_("ice-bin", ["h2o-s"], 1_000_000, "mmol"),
            bin_("ilmenite-bin", ["fetio3-s"], 1_000_000, "mmol"),
            bin_("tank", ["h2o-l", "h2-g", "o2-g"], 1_000_000, "mmol"),
        ],
        "connections": [{"template_id": "pipe", "kind": "FEED", "throughput": R(1, 100), "unit": "mmol", "delay_us": "0"}],
        "environment": [IRRADIANCE],
    }


class DepositVector(Vector):
    """A vector whose genesis has deposits."""

    def __init__(self, *a, deposits: list[dict], **kw):
        super().__init__(*a, **kw)
        self.deposits = deposits

    def save(self) -> None:
        super().save()
        g = json.loads((self.dir / "genesis.json").read_text())
        g["deposits"] = self.deposits
        write(self.dir / "genesis.json", g)


def deposit(did: str, kg: int) -> dict:
    return {"deposit_id": did, "remaining": {"regolith-bank": str(kg)}, "extracted": {}}


def v15() -> list[Vector]:
    e = chain_entries()
    v = DepositVector("V-15", "excavate", "Excavating moves regolith from a deposit to a hopper; one percent is lost as dust",
                      ["LD-PEC-005 §3.3", "LD-PEC-005 §3.5", "LD-PEC-003 §11 P-05"], e,
                      [lot("kits", "inventory", products={"excavator-kit": "1", "hopper-kit": "1", "solar-array-kit": "1"})],
                      environment=["irradiance"], deposits=[deposit("crater", 1_000_000)])
    for k, a in [("solar-array-kit", "solar-1"), ("excavator-kit", "digger-1"), ("hopper-kit", "hopper-1")]:
        v.install(0, k, a)
    v.cmd(0, "CONNECT", connection_id="c-face", template="pipe", from_port="crater.face", to_port="digger-1.face")
    v.cmd(0, "CONNECT", connection_id="c-out", template="pipe", from_port="digger-1.out", to_port="hopper-1.io")
    v.job(0, "job-sun", "generate-solar", "solar-1", 10**9, priority=100)
    v.job(0, "job-dig", "excavate", "digger-1", 10**9, priority=10)
    v.advance(60 * S)
    v.advance(10 * 60 * S)
    # P-05: the dust sink survives a snapshot and restore, and keeps counting.
    v.snapshot("mid")
    v.restore("mid")
    v.advance(30 * 60 * S)
    return [v]


def v16() -> list[Vector]:
    e = chain_entries()
    v = DepositVector("V-16", "mining-chain", "Dig, beneficiate, melt and split: elements are conserved across deposits, lots and sinks",
                      ["LD-PEC-005 §3", "LD-PEC-001 §7.3"], e,
                      [lot("kits", "inventory", products={"excavator-kit": "1", "beneficiator-kit": "1", "melter-kit": "1", "electrolyzer-kit": "1",
                                                          "solar-array-kit": "1", "hopper-kit": "1", "ice-bin-kit": "1", "ilmenite-bin-kit": "1",
                                                          "tank-kit": "3"})],
                      environment=["irradiance"], deposits=[deposit("crater", 1_000_000)])
    for k, a in [("solar-array-kit", "solar-1"), ("excavator-kit", "digger-1"), ("beneficiator-kit", "sorter-1"), ("melter-kit", "melter-1"),
                 ("electrolyzer-kit", "splitter-1"), ("hopper-kit", "hopper-1"), ("ice-bin-kit", "ice-1"), ("ilmenite-bin-kit", "ilmenite-1"),
                 ("tank-kit", "water-tank"), ("tank-kit", "h2-tank"), ("tank-kit", "o2-tank")]:
        v.install(0, k, a)
    for i, (frm, to) in enumerate([("crater.face", "digger-1.face"), ("digger-1.out", "hopper-1.io"), ("hopper-1.io", "sorter-1.feed"),
                                   ("sorter-1.ice", "ice-1.io"), ("sorter-1.ilmenite", "ilmenite-1.io"), ("ice-1.io", "melter-1.ice"),
                                   ("melter-1.water", "water-tank.io"), ("water-tank.io", "splitter-1.water"), ("splitter-1.h2", "h2-tank.io"),
                                   ("splitter-1.o2", "o2-tank.io")]):
        v.cmd(0, "CONNECT", connection_id=f"c-{i}", template="pipe", from_port=frm, to_port=to)
    v.job(0, "job-sun", "generate-solar", "solar-1", 10**9, priority=100)
    for jid, process, m in [("job-dig", "excavate", "digger-1"), ("job-sort", "beneficiate", "sorter-1"), ("job-melt", "melt-ice", "melter-1"),
                            ("job-split", "electrolyze-water", "splitter-1")]:
        v.job(0, jid, process, m, 10**9, priority=10)
    for minutes in (5, 30, 120):
        v.advance(minutes * 60 * S)
    return [v]


# ---------------------------------------------------------------- admission vectors
def admission(vid: str, slug: str, title: str, refs: list[str], entries: dict, expected: dict) -> None:
    d = ld.ROOT / "vectors" / f"{vid}-{slug}"
    if d.exists():
        shutil.rmtree(d)
    cat = d / "catalog"
    for key, items in entries.items():
        for item in items:
            kind = [k for k, v in ld.CATALOG_KINDS.items() if v[2] == key][0]
            write(cat / key / f"{item[ld.CATALOG_KINDS[kind][1]]}.json", item)
    write(cat / "manifest.json", ld.manifest_for(f"vector-{vid[:4].lower()}", ld.read_catalog_entries(cat)))
    write(d / "vector.json", {"id": vid, "title": title, "kind": "ADMISSION", "spec_refs": refs, "pset_version": "0",
                              "numeric_profile": "provisional-u64-i128", "status": "DRAFT"})
    write(d / "expected" / "admission.json", expected)
    print(f"wrote {d.relative_to(ld.ROOT)}")


def minimal(processes: list[dict]) -> dict:
    return {"elements": elements(), "units": units(), "substances": substances(), "processes": processes,
            "machines": [machine("m", [p["process_id"] for p in processes], R(1, 1000), [("ice", "MATERIAL", "IN"), ("water", "MATERIAL", "OUT")])]}


def admissions() -> None:
    admission("P-03a", "phase-ice-to-water", "PHASE ice to water that draws more than the latent heat is accepted",
              ["LD-PEC-003 §4 PHASE", "LD-PEC-005 §3.6"], minimal([melt()]), {"verdict": "ACCEPTED"})
    bad = melt()
    bad["process_id"] = "melt-to-hydrogen"
    bad["stages"][0]["ops"][0] = {"op": "PHASE", "from": "h2o-s", "to": "h2-g", "quantity": EXTENT}
    bad["ports"]["out"] = [{"port": "water", "accepts": ["h2-g"]}]
    bad["edges"][1]["species"] = ["h2-g"]
    admission("P-03b", "phase-formula-mismatch", "PHASE between species with different formulas is rejected",
              ["LD-PEC-003 §4 PHASE"], minimal([bad]),
              {"verdict": "REJECTED", "failed_check": "ELEMENT_BALANCE", "subject": "melt-to-hydrogen", "detail": "PHASE h2o-s -> h2-g: formulas differ"})
    cheap = melt(5)
    cheap["process_id"] = "melt-on-the-cheap"
    admission("P-13", "net-energy", "PHASE that absorbs more latent heat than the process draws, with no external source, is rejected",
              ["LD-PEC-003 §5", "LD-PEC-003 §11 P-13", "LD-PEC-005 §3.6"], minimal([cheap]),
              {"verdict": "REJECTED", "failed_check": "ENERGY_BALANCE", "subject": "melt-on-the-cheap",
               "detail": "absorbs 6.01 J per unit of latent heat but draws 5 J"})


def main() -> int:
    for v in v15() + v16():
        v.save()
    admissions()
    return 0


if __name__ == "__main__":
    sys.exit(main())
