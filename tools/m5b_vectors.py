"""Trade vectors (LD-PEC-004 Amendment 6): landing pads, MOVE_LOT, EXPORT, ACCEPT_IMPORT,
delivery and the trade ledgers, V-39 to V-55.

    python tools/m5b_vectors.py --engine <engine-cli>

Vectors stay single-claim (A6-9). A vector that accepts an import carries, inline in its
ACCEPT_IMPORT command, the certificate the export vector it names emitted. The engine is
needed to write them: this tool runs each exporting vector's commands through it and
takes the certificates from its SHIPMENT_DEPARTED events. A pair is named `V-NNa` (the
exporter) and `V-NNb` (the importer); tools/check_trade_pairs.py checks the pairs'
ledgers once expected/ is written.

Masses are chosen so that every trip energy E is a whole number of joules, which keeps
the expected files readable; a fractional E would sit in the sink's residual.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shlex
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ld  # noqa: E402
from m1_vectors import R, S, Vector, kit, lot, machine, write  # noqa: E402
from m3b_vectors import FRESH  # noqa: E402
from m4a_vectors import core_entries  # noqa: E402

DAY = 86_400 * S
TRANSIT = 2 * DAY
WORLD = "trade-world"
A, B = "claim-a", "claim-b"
POLICY = {"policy_id": "accept-all-v0", "evidence_hash": hashlib.sha256(b"ld vector evidence").hexdigest()}


def route(rid: str, frm: str, to: str, epk: dict, transit: int = TRANSIT) -> dict:
    return {"route_id": rid, "from_claim": frm, "to_claim": to, "transit_us": str(transit), "energy_per_kg": epk}


# One route table for every trade vector. `a-to-b-fine` moves milligram-precise cargo
# (a reactor core) at a whole number of joules; `a-to-b-free` costs nothing.
ROUTES = [
    route("a-to-b", A, B, R(1000)),
    route("a-to-b-fine", A, B, R(10**6)),
    route("a-to-b-free", A, B, R(0)),
    route("b-to-a", B, A, R(1000)),
]
TRADE = {"epoch_us": "0", "routes": ROUTES}


# ---------------------------------------------------------------- catalog
def store(capacity_j: int) -> dict:
    return {"capacity": {"amount": R(capacity_j), "unit": "j"}, "max_charge": {"amount": R(5000), "unit": "w"},
            "max_discharge": {"amount": R(5000), "unit": "w"}, "charge_efficiency": R(9, 10), "heat_sink": "rover-heat"}


def trade_entries() -> dict:
    """V-30's reactor plant, plus iron in kilograms, an unweighable widget, a rover (a carrier
    with a 1 GJ store and a 500 kg payload), a hopper, a landing pad and two bins."""
    e = core_entries()
    e["units"] = e["units"] + [{"unit_id": "kg", "dimension": "mass", "scale": R(1)},
                               {"unit_id": "pcs", "dimension": "count", "scale": R(1)}]
    e["substances"] = e["substances"] + [
        {"substance_id": "fe-s", "formula": {"fe": "1"}, "phase": "solid", "quantity_unit": "kg"},
        {"substance_id": "widget", "formula": {"fe": "1"}, "phase": "solid", "quantity_unit": "pcs"},
    ]
    rover = machine("rover", [], R(1, S), [("power", "ELECTRICAL", "IN")])
    rover["energy_store"] = store(10**9)
    rover["embodied"] = {"fe-s": "200"}
    hopper = machine("hopper", [], R(1, S), [("io", "MATERIAL", "OUT")], condition=[
        {"wear_at": "0", "capacity_factor": R(1)}, {"wear_at": "100", "capacity_factor": R(0)}])
    hopper["embodied"] = {"fe-s": "50"}
    e["machines"] = e["machines"] + [rover, hopper]
    rover_kit = kit("rover-kit", "MACHINE", "rover")
    rover_kit["embodied"] = {"fe-s": "200"}
    rover_kit["carrier"] = {"payload": {"amount": "500", "unit": "kg"}}
    hopper_kit = kit("hopper-kit", "MACHINE", "hopper")
    hopper_kit["embodied"] = {"fe-s": "50"}
    e["products"] = e["products"] + [rover_kit, hopper_kit, kit("pad-kit", "BUFFER", "pad"), kit("ore-bin-kit", "BUFFER", "ore-bin"),
                                     kit("widget-bin-kit", "BUFFER", "widget-bin")]
    e["buffers"] = e["buffers"] + [
        {"template_id": "pad", "kind": "LANDING", "accepts": [], "capacity": {"amount": "1000", "unit": "kg"}},
        {"template_id": "ore-bin", "accepts": ["fe-s"], "capacity": {"amount": "100000", "unit": "kg"}},
        {"template_id": "widget-bin", "accepts": ["widget"], "capacity": {"amount": "1000", "unit": "pcs"}},
    ]
    e["connections"] = e["connections"] + [
        {"template_id": "cart", "kind": "CONVEYOR", "throughput": R(1, 1000), "unit": "kg", "delay_us": str(2 * S)},
        {"template_id": "crate-belt", "kind": "CONVEYOR", "throughput": R(1, 1000), "unit": "pcs", "delay_us": str(2 * S)},
    ]
    return e


def tlot(lot_id: str, location: str = "inventory", composition=None, products=None, charge=None, wear=None, core=None) -> dict:
    out = lot(lot_id, location, composition, products)
    for k, v in (("charge", charge), ("wear", wear), ("core", core)):
        if v is not None:
            out[k] = v
    return out


def rover(lot_id: str = "rover", charge: int = 500_000_000) -> dict:
    return tlot(lot_id, products={"rover-kit": "1"}, charge=R(charge))


class TradeVector(Vector):
    """A vector whose genesis is a claim of the trade world (or a solo claim, `trade=None`)."""

    def __init__(self, vid, slug, title, refs, lots, claim=A, trade=TRADE, entries=None):
        super().__init__(vid, slug, title, ["LD-PEC-004 A6"] + refs, entries or trade_entries(), lots)
        self.claim, self.trade = claim, trade

    def save(self) -> None:
        super().save()
        # Every claim of the trade world runs the one catalog the world file pins (A6-1).
        manifest = ld.manifest_for("vector-trade-world", ld.read_catalog_entries(self.dir / "catalog"))
        write(self.dir / "catalog" / "manifest.json", manifest)
        g = ld.load_json(self.dir / "genesis.json")
        g["catalog_hash"] = ld.catalog_hash(manifest)
        g["world_id"] = WORLD
        g["claim_id"] = self.claim
        if self.trade is not None:
            g["trade"] = self.trade
        write(self.dir / "genesis.json", g)

    def pad(self, t: int = 0, as_id: str = "pad-1") -> None:
        self.install(t, "pad-kit", as_id)

    def move(self, t: int, lot_id: str, to: str = "pad-1", products: dict | None = None) -> None:
        args = {"lot_id": lot_id, "to": to}
        if products:
            args["products"] = products
        self.cmd(t, "MOVE_LOT", **args)

    def export(self, t: int, export_id: str, carrier: str, lots=(), contents=None, route_id="a-to-b", peer=B, landing="pad-1") -> None:
        args = {"export_id": export_id, "landing": landing, "carrier_lot": carrier, "peer_claim": peer, "route_id": route_id}
        if lots:
            args["lots"] = list(lots)
        if contents:
            args["contents"] = contents
        self.cmd(t, "EXPORT", **args)

    def accept(self, t: int, cert: dict, landing: str = "pad-1") -> None:
        self.cmd(t, "ACCEPT_IMPORT", certificate=cert, landing=landing, policy=POLICY)


# ---------------------------------------------------------------- engine driver
class Engine:
    def __init__(self, binary: str):
        self.p = subprocess.Popen(shlex.split(binary), stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
        self.n = 0

    def call(self, method: str, params: dict | None = None) -> dict:
        self.n += 1
        self.p.stdin.write(json.dumps({"id": str(self.n), "method": method, "params": params or {}}) + "\n")
        self.p.stdin.flush()
        r = json.loads(self.p.stdout.readline())
        if r["method"] == "error":
            raise RuntimeError(f"{method}: {r['error']}")
        return r["result"]

    def close(self) -> None:
        self.p.stdin.close()
        self.p.wait()


ENGINE: str = ""


def certificates(v: TradeVector) -> list[dict]:
    """The certificates a saved vector's commands emit, in order."""
    e = Engine(ENGINE)
    e.call("create", {"genesis": ld.load_json(v.dir / "genesis.json"), "catalog": ld.bundle_for(v.dir / "catalog")})
    for c in ld.load_jsonl(v.dir / "commands.jsonl"):
        e.call("advance_to", {"t_us": c["effective_us"]})
        e.call("submit", {"command": c})
    page = e.call("events_since", {"cursor": "0", "limit": "1000000"})
    e.close()
    return [ev["certificate"] for ev in page["events"] if ev["kind"] == "SHIPMENT_DEPARTED"]


def arrive(cert: dict) -> int:
    return int(cert["arrive_us"])


# ---------------------------------------------------------------- vectors
def iron_export(vid: str, slug: str, title: str, refs=(), by: dict | None = None) -> TradeVector:
    """A stages 100 kg of iron and a charged rover on its pad and ships them to B on a
    two-day route: E = 1000 J/kg x (200 + 100) kg = 300 kJ."""
    v = TradeVector(vid, slug, title, list(refs), [tlot("kits", products={"pad-kit": "1"}), tlot("iron", composition={"fe-s": "100"}), rover()])
    v.pad()
    v.move(0, "iron")
    v.move(0, "rover")
    v.export(0, "x-1", "rover", lots=["iron"])
    if by is not None:
        for c in v.commands:
            c["issued_by"] = by
    return v


def importer(vid: str, slug: str, title: str, refs=(), extra_lots=()) -> TradeVector:
    return TradeVector(vid, slug, title, list(refs), [tlot("kits", products={"pad-kit": "1"}), *extra_lots], claim=B)


def v39_v40_v41_v42() -> list[TradeVector]:
    a = iron_export("V-39", "export", "EXPORT debits the pad once, sinks the trip energy and delivers at arrive_us")
    a.advance(TRANSIT - 1)
    a.advance(TRANSIT)
    a.advance(TRANSIT + DAY)
    a.save()
    cert = certificates(a)[0]

    b = importer("V-40", "accept-import", "ACCEPT_IMPORT credits the pad once, with the carrier and its remaining charge", ["V-39"])
    b.pad()
    b.accept(arrive(cert), cert)
    b.advance(arrive(cert) + S)

    dup = importer("V-41", "duplicate-import", "The same certificate twice: duplicate-import, state unchanged", ["V-40"])
    dup.pad()
    dup.accept(arrive(cert), cert)
    dup.accept(arrive(cert), cert)
    dup.advance(arrive(cert) + S)

    early = importer("V-42", "not-arrived", "A certificate one microsecond before arrive_us is not-arrived, then accepted at it", ["V-40"])
    early.pad()
    early.accept(arrive(cert) - 1, cert)
    early.accept(arrive(cert), cert)
    early.advance(arrive(cert) + S)
    return [a, b, dup, early]


def v43() -> list[TradeVector]:
    v = TradeVector("V-43", "export-refusals", "EXPORT refusals: insufficient charge, overweight, no route, unstaged lot, insufficient contents, empty shipment",
                    [], [tlot("kits", products={"pad-kit": "1"}), tlot("iron", composition={"fe-s": "50"}), tlot("heavy", composition={"fe-s": "501"}),
                         tlot("held-back", composition={"fe-s": "10"}), rover(), rover("weak", 1000)])
    v.pad()
    for k in ("iron", "heavy", "rover", "weak"):
        v.move(0, k)
    v.export(0, "x-1", "weak", lots=["iron"])            # insufficient-charge: E = 250 kJ
    v.export(0, "x-1", "rover", lots=["heavy"])          # overweight: 501 kg > 500 kg
    v.export(0, "x-1", "rover", lots=["iron"], route_id="b-to-a", peer=B)   # no-route: b-to-a leaves B
    v.export(0, "x-1", "rover", lots=["iron"], peer="claim-c")              # no-route: no such peer
    v.export(0, "x-1", "rover", lots=["held-back"])     # lot-not-staged: still in the hold
    v.export(0, "x-1", "rover", contents={"fe-s": "1"})  # insufficient: the pad holds no loose iron
    v.export(0, "x-1", "rover")                          # empty-shipment
    v.export(0, "x-1", "rover", lots=["iron"])           # accepted
    v.advance(TRANSIT + S)
    return [v]


def v44() -> list[TradeVector]:
    """A ships iron to B; B accepts and ships the rover back with 18.015 kg of water
    (E = 1000 x 218.015 kg = 218,015 J); A accepts."""
    a1 = iron_export("V-44a", "pair-a", "Pair: A ships iron, then accepts the rover back with water")
    a1.save()
    c1 = certificates(a1)[0]
    b = importer("V-44b", "pair-b", "Pair: B accepts the iron and ships the rover back with water", extra_lots=[tlot("water", composition={"h2o-l": "1000000"})])
    b.pad()
    b.accept(arrive(c1), c1)
    b.move(arrive(c1), "water")
    b.export(arrive(c1), "y-1", "imp-1-carrier", lots=["water"], route_id="b-to-a", peer=A)
    b.advance(arrive(c1) + TRANSIT + S)
    b.save()
    c2 = certificates(b)[0]
    a = iron_export("V-44a", "pair-a", "Pair: A ships iron, then accepts the rover back with water")
    a.accept(arrive(c2), c2)
    a.advance(arrive(c2) + S)
    return [a, b]


def v45() -> list[TradeVector]:
    v = iron_export("V-45", "restore-in-transit", "A claim restored with a shipment in transit delivers it at the same time", ["V-39"])
    v.advance(DAY)
    v.snapshot("transit")
    v.advance(TRANSIT + DAY)
    v.restore("transit")
    v.advance(TRANSIT + DAY)
    return [v]


def tamper(cert: dict, **changes) -> dict:
    c = copy.deepcopy(cert)
    c.update(changes)
    return c


def v46(cert: dict) -> list[TradeVector]:
    t = arrive(cert)
    v = importer("V-46", "import-refusals", "ACCEPT_IMPORT refusals: wrong world, wrong epoch, wrong destination, catalog mismatch, route mismatch, bad spend id, a full pad",
                 ["V-39"], extra_lots=[tlot("slag", composition={"fe-s": "800"})])
    v.pad()
    v.accept(t, tamper(cert, world="other-world"))
    v.accept(t, tamper(cert, epoch_us="1"))
    v.accept(t, tamper(cert, peer_claim="claim-c"))
    v.accept(t, tamper(cert, catalog_hash="0" * 64))
    v.accept(t, tamper(cert, arrive_us=str(t + 1)))
    v.accept(t, tamper(cert, route_id="b-to-a"))
    v.accept(t, tamper(cert, n="2"))
    v.move(t, "slag")                                # 800 kg on a 1000 kg pad
    v.accept(t, cert)                                # needs 300 kg: REJECTED_CAPACITY
    v.move(t, "slag", to="inventory")
    v.accept(t, cert)                                # accepted
    v.advance(t + S)
    return [v]


def v47() -> list[TradeVector]:
    v = TradeVector("V-47", "move-lot", "MOVE_LOT: splits, whole moves, and its refusals",
                    [], [tlot("kits", products={"pad-kit": "1", "ore-bin-kit": "1"}), tlot("cargo", products={"rover-kit": "1", "hopper-kit": "1"}),
                         tlot("worn", products={"hopper-kit": "1"}, wear=R(5)), tlot("slag", composition={"fe-s": "750"}),
                         tlot("ore", "ore-bin-1", {"fe-s": "300"})])
    v.pad()
    v.install(0, "ore-bin-kit", "ore-bin-1")
    v.cmd(0, "CONNECT", connection_id="cart-1", template="cart", from_port="ore-bin-1.io", to_port="pad-1.io")
    v.move(0, "cargo", products={"rover-kit": "1"})     # mv-1
    v.move(0, "cargo", products={"hopper-kit": "1"})    # mv-2; the cargo lot is used up
    v.move(0, "worn")                                   # whole: keeps its id and wear
    v.move(0, "worn", to="inventory", products={"hopper-kit": "1"})   # not-splittable
    v.move(0, "mv-1", to="ore-bin-1")                   # not-a-landing: a STORE buffer
    v.move(0, "mv-1")                                   # not-a-landing: already there
    v.cmd(0, "TRANSFER_LOCAL", connection_id="cart-1", species="fe-s", amount=100)   # lot-1 in transit, 100 kg reserved
    v.move(0, "lot-1", to="inventory")                  # lot-busy
    v.move(0, "slag")                                   # 200 + 50 + 50 + 100 reserved + 750 > 1000: REJECTED_CAPACITY
    v.move(0, "mv-2", products={"hopper-kit": "1"}, to="inventory")   # mv-3: the counter advances only on splits
    v.advance(3 * S)
    v.move(3 * S, "slag")                               # 350 kg staged and arrived + 750: still no room
    return [v]


def v48() -> list[TradeVector]:
    """A ships a reactor kit carrying a core and a worn hopper kit on the fine route
    (1 MJ/kg): E = 10^6 x (200 + 50 + 0.270027) kg. B accepts and installs the reactor."""
    def a_side() -> TradeVector:
        a = TradeVector("V-48a", "kits-pair-a", "Pair: A ships a reactor kit with its core and a worn hopper kit", [],
                        [tlot("kits", products={"pad-kit": "1"}), tlot("reactor", products={"reactor-kit": "1"}, core={FRESH: "1000"}),
                         tlot("worn", products={"hopper-kit": "1"}, wear=R(5)), rover()])
        a.pad()
        for k in ("reactor", "worn", "rover"):
            a.move(0, k)
        a.export(0, "x-1", "rover", lots=["reactor", "worn"], route_id="a-to-b-fine")
        a.advance(TRANSIT + S)
        return a
    a = a_side()
    a.save()
    cert = certificates(a)[0]
    b = importer("V-48b", "kits-pair-b", "Pair: B accepts the kits and installs the reactor with its core")
    b.pad()
    b.accept(arrive(cert), cert)
    b.cmd(arrive(cert), "INSTALL", lot_id="imp-1-1", product="reactor-kit", location="pad-b", as_id="reactor-1")
    b.advance(arrive(cert) + S)
    return [a, b]


def v49() -> list[TradeVector]:
    v = TradeVector("V-49", "pads-and-conveyors", "Pads take conveyor deliveries by mass; contents export; unweighable species and FEEDs are refused",
                    [], [tlot("kits", products={"pad-kit": "1", "ore-bin-kit": "1", "widget-bin-kit": "1", "hopper-kit": "1"}),
                         tlot("ore", "ore-bin-1", {"fe-s": "300"}), tlot("gadgets", "widget-bin-1", {"widget": "10"}),
                         tlot("slag", composition={"fe-s": "901"}), tlot("ballast", composition={"fe-s": "600"}), rover()])
    v.pad()
    v.install(0, "ore-bin-kit", "ore-bin-1")
    v.install(0, "widget-bin-kit", "widget-bin-1")
    v.install(0, "hopper-kit", "hopper-1")
    v.cmd(0, "CONNECT", connection_id="cart-1", template="cart", from_port="ore-bin-1.io", to_port="pad-1.io")
    v.cmd(0, "CONNECT", connection_id="crate-1", template="crate-belt", from_port="widget-bin-1.io", to_port="pad-1.io")
    v.cmd(0, "TRANSFER_LOCAL", connection_id="cart-1", species="fe-s", amount=100)   # 100 kg reserved on the pad
    v.move(0, "slag")                                   # 901 + 100 reserved > 1000: REJECTED_CAPACITY
    v.move(0, "ballast")                                # 600 + 100 reserved fits
    v.move(0, "ballast", to="inventory")
    v.cmd(0, "TRANSFER_LOCAL", connection_id="crate-1", species="widget", amount=1)   # unshippable-unit
    v.cmd(0, "CONNECT", connection_id="pipe-1", template="pipe", from_port="hopper-1.io", to_port="pad-1.io")   # landing-feed
    v.advance(3 * S)
    v.move(3 * S, "rover")
    v.export(3 * S, "x-1", "rover", contents={"fe-s": "100"})   # the arrived contents
    v.advance(3 * S + TRANSIT + S)
    return [v]


def v50(cert: dict) -> list[TradeVector]:
    v = TradeVector("V-50a", "export-refusals-2", "EXPORT refusals: duplicate-export after delivery, duplicate-lot, not-a-carrier",
                    [], [tlot("kits", products={"pad-kit": "1"}), tlot("iron", composition={"fe-s": "100"}), tlot("iron-2", composition={"fe-s": "50"}),
                         tlot("twins", products={"rover-kit": "2"}), tlot("hopper", products={"hopper-kit": "1"}),
                         tlot("dirty", composition={"fe-s": "10"}, products={"rover-kit": "1"}), rover(), rover("rover-2")])
    v.pad()
    for k in ("iron", "iron-2", "rover", "rover-2"):
        v.move(0, k)
    v.export(0, "x-1", "rover", lots=["iron"])
    for k in ("twins", "hopper", "dirty"):              # room freed by the first export
        v.move(0, k)
    v.advance(TRANSIT + S)
    t = TRANSIT + S
    v.export(t, "x-1", "rover-2", lots=["iron-2"])          # duplicate-export, after delivery
    v.export(t, "x-2", "rover-2", lots=["iron-2", "iron-2"])   # duplicate-lot
    v.export(t, "x-2", "rover-2", lots=["rover-2"])          # duplicate-lot: the carrier listed as cargo
    v.export(t, "x-2", "twins", lots=["iron-2"])             # not-a-carrier: two units
    v.export(t, "x-2", "hopper", lots=["iron-2"])            # not-a-carrier: not a carrier product
    v.export(t, "x-2", "dirty", lots=["iron-2"])             # not-a-carrier: composition aboard
    v.export(t, "x-2", "rover-2", lots=["iron-2"])           # accepted, n = 2
    v.advance(t + S)
    solo = TradeVector("V-50b", "solo-refusals", "A solo claim refuses EXPORT and ACCEPT_IMPORT: not-a-trade-world", [],
                       [tlot("kits", products={"pad-kit": "1"}), tlot("iron", composition={"fe-s": "100"}), rover()], trade=None)
    solo.pad()
    solo.move(0, "iron")
    solo.move(0, "rover")
    solo.export(0, "x-1", "rover", lots=["iron"])
    solo.accept(0, cert)
    solo.advance(S)
    return [v, solo]


def v51(cert: dict) -> list[TradeVector]:
    t = arrive(cert)
    two_worn = copy.deepcopy(cert)
    two_worn["manifest"]["lots"] = [{"products": {"hopper-kit": "2"}, "wear": R(5)}]
    unknown = copy.deepcopy(cert)
    unknown["manifest"]["contents"] = {"unobtainium": "1"}
    overcharged = copy.deepcopy(cert)
    overcharged["carrier"]["charge"] = R(10**9 + 1)
    v = importer("V-51", "import-refusals-2", "ACCEPT_IMPORT refusals: bad-manifest three ways; arrive_us at 2^63", ["V-39"])
    v.pad()
    v.accept(t, unknown)
    v.accept(t, overcharged)
    v.accept(t, two_worn)
    v.accept(t, tamper(cert, arrive_us=str(2**63)))     # REJECTED_SCHEMA
    v.accept(t, cert)
    v.advance(t + S)
    return [v]


def v52() -> list[TradeVector]:
    """Two outbound shipments and a conveyor shipment arrive at the same microsecond T, and
    a command is applied at T. Loading 100 kg takes 0.1 s and the cart's delay is 2 s."""
    v = TradeVector("V-52", "same-microsecond", "Conveyor arrival, then deliveries in shipment-id order, then the command",
                    [], [tlot("kits", products={"pad-kit": "1", "ore-bin-kit": "1"}), tlot("ore", "ore-bin-1", {"fe-s": "300"}),
                         tlot("iron", composition={"fe-s": "100"}), tlot("iron-2", composition={"fe-s": "100"}), rover(), rover("rover-2")])
    v.pad()
    v.install(0, "ore-bin-kit", "ore-bin-1")
    v.cmd(0, "CONNECT", connection_id="cart-1", template="cart", from_port="ore-bin-1.io", to_port="pad-1.io")
    for k in ("iron", "iron-2", "rover", "rover-2"):
        v.move(0, k)
    v.export(0, "x-1", "rover", lots=["iron"])
    v.export(0, "x-2", "rover-2", lots=["iron-2"])
    t0 = TRANSIT - 2 * S - S // 10
    v.cmd(t0, "TRANSFER_LOCAL", connection_id="cart-1", species="fe-s", amount=100)
    v.cmd(TRANSIT, "CHECKPOINT", label="t")
    v.advance(TRANSIT + S)
    return [v]


def v53(cert: dict) -> list[TradeVector]:
    t = arrive(cert)
    v = importer("V-53", "import-restore", "After restore: duplicate-import still refused, the next export is n = 2, a reused export_id is refused",
                 ["V-40"], extra_lots=[tlot("water", composition={"h2o-l": "1000000"}), tlot("water-2", composition={"h2o-l": "1000000"}),
                                       rover("rover-b")])
    v.pad()
    v.accept(t, cert)
    v.move(t, "water")
    v.export(t, "y-1", "imp-1-carrier", lots=["water"], route_id="b-to-a", peer=A)
    v.advance(t + S)
    v.snapshot("after")
    v.advance(t + 2 * S)
    v.restore("after")
    t2 = t + 2 * S
    v.accept(t2, cert)                                  # duplicate-import
    v.move(t2, "water-2")
    v.move(t2, "rover-b")
    v.export(t2, "y-1", "rover-b", lots=["water-2"], route_id="b-to-a", peer=A)   # duplicate-export
    v.export(t2, "y-2", "rover-b", lots=["water-2"], route_id="b-to-a", peer=A)   # n = 2
    v.advance(t2 + S)
    return [v]


def v54(cert: dict) -> list[TradeVector]:
    host = {"origin": "host"}
    a = iron_export("V-54a", "attributed-export", "V-39 with issued_by: the same physical states", ["LD-PEC-004 A5", "V-39"], by=host)
    a.advance(TRANSIT - 1)
    a.advance(TRANSIT)
    a.advance(TRANSIT + DAY)
    b = importer("V-54b", "attributed-import", "V-40 with issued_by: the same physical states", ["LD-PEC-004 A5", "V-40"])
    b.pad()
    b.accept(arrive(cert), cert)
    b.advance(arrive(cert) + S)
    for c in b.commands:
        c["issued_by"] = host
    return [a, b]


def v55() -> list[TradeVector]:
    """A rover charged with exactly E (200 + 100 kg x 1000 J/kg = 300 kJ) leaves empty; a
    free route creates no sink; a lot moved back to the hold keeps its id."""
    v = TradeVector("V-55", "edges", "Charge exactly E; a zero-energy route; MOVE_LOT back to the hold",
                    [], [tlot("kits", products={"pad-kit": "1"}), tlot("iron", composition={"fe-s": "100"}), tlot("iron-2", composition={"fe-s": "100"}),
                         tlot("spare", composition={"fe-s": "5"}), rover("exact", 300_000), rover("free", 1000)])
    v.pad()
    for k in ("iron", "iron-2", "spare", "exact", "free"):
        v.move(0, k)
    v.move(0, "spare", to="inventory")                  # back to the hold, same id
    v.export(0, "x-1", "exact", lots=["iron"])          # charge left: "0"
    v.export(0, "x-2", "free", lots=["iron-2"], route_id="a-to-b-free")   # no sink
    v.advance(TRANSIT + S)
    return [v]


def main() -> int:
    global ENGINE
    p = argparse.ArgumentParser()
    p.add_argument("--engine", required=True, help="an I-1 engine command line, to take certificates from export vectors")
    ENGINE = p.parse_args().engine
    out: list[TradeVector] = []
    first = v39_v40_v41_v42()
    cert = certificates(first[0])[0]
    out += first
    out += v43() + v44() + v45() + v46(cert) + v47() + v48() + v49() + v50(cert) + v51(cert) + v52() + v53(cert) + v54(cert) + v55()
    for v in out:
        v.save()
    return 0


if __name__ == "__main__":
    sys.exit(main())
