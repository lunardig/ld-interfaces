"""Checks the trade vectors' exporting and importing pairs (LD-PEC-004 A6-9) from their
expected/ outputs:

1. the exporter's `trade.exported` equals the importer's `trade.imported`, element by
   element and in charge;
2. each `trade-<route>` sink equals the trips' E, recomputed here from the catalog's masses
   (E = energy_per_kg x (carrier + cargo), A6-3, A6-4);
3. the pair's genesis element totals equal everything both claims hold plus both claims'
   sinks;

and that V-54's attributed runs reach V-39's and V-40's physical states step by step.

A double count in either ledger then shows up as a number, not as a passing test.

    python tools/check_trade_pairs.py
"""
from __future__ import annotations

import sys
from collections import Counter
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ld  # noqa: E402

VECTORS = ld.ROOT / "vectors"
# (exporter, importer) pairs whose final states are compared. V-44 ships both ways.
PAIRS = [("V-39", "V-40"), ("V-44a", "V-44b"), ("V-44b", "V-44a"), ("V-48a", "V-48b"), ("V-54a", "V-54b")]
WORLDS = [("V-39", "V-40"), ("V-44a", "V-44b"), ("V-48a", "V-48b"), ("V-54a", "V-54b")]


def vdir(vid: str) -> Path:
    return next(p for p in VECTORS.iterdir() if p.name.startswith(vid + "-"))


def q(r) -> Fraction:
    return Fraction(int(r["n"]), int(r["d"])) if isinstance(r, dict) else Fraction(int(r))


class Catalog:
    def __init__(self, d: Path):
        b = ld.bundle_for(d / "catalog")
        self.units = {u["unit_id"]: u for u in b["units"]}
        self.elements = {e["element_id"]: q(e["molar_mass"]) for e in b["elements"]}
        self.subs = {s["substance_id"]: s for s in b["substances"]}
        self.products = {p["product_id"]: p for p in b["products"]}
        self.kits = {(p["installs_as"]["kind"], p["installs_as"]["template"]): p for p in b["products"] if p.get("installs_as")}

    def atoms(self, out: Counter, amounts: dict, times: int = 1) -> None:
        for sp, n in (amounts or {}).items():
            for el, k in self.subs[sp]["formula"].items():
                out[el] += int(n) * int(k) * times

    def product_atoms(self, out: Counter, product: str, n: int) -> None:
        self.atoms(out, self.products[product]["embodied"], n)

    def kg(self, amounts: dict) -> Fraction:
        total = Fraction(0)
        for sp, n in (amounts or {}).items():
            s = self.subs[sp]
            u = self.units[s["quantity_unit"]]
            x = int(n) * q(u["scale"])
            if u["dimension"] == "mass":
                total += x
            elif u["dimension"] == "amount":
                total += x * sum(self.elements[el] * int(k) for el, k in s["formula"].items()) / 1000
            else:
                raise ValueError(f"{sp} can't be weighed")
        return total

    def lot_kg(self, lot: dict) -> Fraction:
        m = self.kg(lot.get("composition")) + self.kg(lot.get("core"))
        for p, n in lot.get("products", {}).items():
            m += int(n) * self.kg(self.products[p]["embodied"])
        return m


def held(cat: Catalog, st: dict) -> Counter:
    """Every element the claim holds or has sunk, shipments in transit included."""
    out: Counter = Counter()
    for lot in st["lots"]:
        cat.atoms(out, lot.get("composition"))
        cat.atoms(out, lot.get("core"))
        for p, n in lot.get("products", {}).items():
            cat.product_atoms(out, p, int(n))
    for d in st.get("deposits", []):
        cat.atoms(out, d["remaining"])
    for k in st.get("sinks", []):
        cat.atoms(out, k.get("totals"))
    for m in st["machines"]:
        cat.atoms(out, cat.kits[("MACHINE", m["blueprint"])]["embodied"])
    for b in st["buffers"]:
        kit = cat.kits.get(("BUFFER", b.get("template")))
        if kit:   # a machine's core is part of its machine (LD-PEC-004 A2-3)
            cat.atoms(out, kit["embodied"])
    for s in st.get("shipments", []):
        man = s["manifest"]
        cat.atoms(out, man["contents"])
        for lot in man["lots"]:
            cat.atoms(out, lot.get("composition"))
            cat.atoms(out, lot.get("core"))
            for p, n in lot["products"].items():
                cat.product_atoms(out, p, int(n))
        cat.product_atoms(out, s["carrier"]["product"], 1)
    return out


def genesis_atoms(cat: Catalog, g: dict) -> Counter:
    out: Counter = Counter()
    for lot in g["starting_lots"]:
        cat.atoms(out, lot.get("composition"))
        cat.atoms(out, lot.get("core"))
        for p, n in lot.get("products", {}).items():
            cat.product_atoms(out, p, int(n))
    for d in g.get("deposits", []):
        cat.atoms(out, d["remaining"])
    return out


def ledger(st: dict, side: str) -> tuple[dict, Fraction]:
    led = st["trade"][side]
    return ({k: q(v) for k, v in led["elements"].items()}, q(led["charge"]))


def check() -> list[str]:
    fails = []
    for a, b in PAIRS:
        sa = ld.load_json(vdir(a) / "expected" / "state.json")
        sb = ld.load_json(vdir(b) / "expected" / "state.json")
        if ledger(sa, "exported") != ledger(sb, "imported"):
            fails.append(f"{a} -> {b}: exported {ledger(sa, 'exported')} != imported {ledger(sb, 'imported')}")
    for vid in sorted({x for p in PAIRS for x in p}):
        d = vdir(vid)
        cat = Catalog(d)
        routes = {r["route_id"]: r for r in ld.load_json(d / "genesis.json")["trade"]["routes"]}
        expect: Counter = Counter()
        for ev in ld.load_jsonl(d / "expected" / "events.jsonl"):
            if ev["kind"] != "SHIPMENT_DEPARTED":
                continue
            c = ev["certificate"]
            cargo = cat.kg(c["manifest"]["contents"]) + sum(cat.lot_kg(lt) for lt in c["manifest"]["lots"])
            carrier = cat.lot_kg({"products": {c["carrier"]["product"]: "1"}})
            expect[f"trade-{c['route_id']}"] += q(routes[c["route_id"]]["energy_per_kg"]) * (carrier + cargo)
        st = ld.load_json(d / "expected" / "state.json")
        res = {(r["owner"], r["accumulator"]): q(r["value"]) for r in st.get("residuals", [])}
        got = {k["sink_id"]: int(k["energy"]) + res.get((k["sink_id"], "energy"), 0)
               for k in st.get("sinks", []) if k["sink_id"].startswith("trade-")}
        want = {k: v for k, v in expect.items() if v != 0}
        if got != want:
            fails.append(f"{vid}: trade sinks {got} != trip energy {want}")
    for a, b in WORLDS:
        da, db = vdir(a), vdir(b)
        cat = Catalog(da)
        g = genesis_atoms(cat, ld.load_json(da / "genesis.json")) + genesis_atoms(cat, ld.load_json(db / "genesis.json"))
        h = held(cat, ld.load_json(da / "expected" / "state.json")) + held(cat, ld.load_json(db / "expected" / "state.json"))
        if +g != +h:
            fails.append(f"{a} + {b}: genesis {dict(g)} != held {dict(h)}")
    # V-54: attribution changes no physical state (A5-1, A6-8).
    for plain, attributed in (("V-39", "V-54a"), ("V-40", "V-54b")):
        hp = [h["state_hash"] for h in ld.load_json(vdir(plain) / "expected" / "hashes.json")]
        ha = [h["state_hash"] for h in ld.load_json(vdir(attributed) / "expected" / "hashes.json")]
        if hp != ha:
            fails.append(f"{attributed}: state hashes differ from {plain}'s")
        for ev in ld.load_jsonl(vdir(attributed) / "expected" / "events.jsonl"):
            if ev["kind"] in ("SHIPMENT_DEPARTED", "SHIPMENT_DELIVERED", "IMPORT_ACCEPTED") and "issued_by" in ev:
                fails.append(f"{attributed}: {ev['kind']} carries issued_by")
    return fails


def main() -> int:
    fails = check()
    for f in fails:
        print("FAIL", f)
    print(f"{len(PAIRS)} pairs, {len(fails)} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
