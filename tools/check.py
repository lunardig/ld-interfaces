"""Repository checks run by CI. Exit status is nonzero on any failure.

1. Every schema is a valid JSON Schema 2020-12 document and every $ref resolves.
2. Every example and vector file validates against its definition.
3. Catalog manifests match their entry files (hashes recomputed).
4. Admission vectors whose verdict depends only on REACT element balance agree with a
   minimal balance check. This is a sanity check on the vectors themselves; the catalog
   validator (W2) and the reference evaluator (W5) are the real implementations.
"""
from __future__ import annotations

import sys
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ld  # noqa: E402

FAILURES: list[str] = []


def fail(msg: str) -> None:
    FAILURES.append(msg)
    print(f"FAIL {msg}")


def ok(msg: str) -> None:
    print(f"ok   {msg}")


def check_schemas(reg) -> None:
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import SchemaError

    for name in ld.SCHEMA_FILES:
        schema = ld.load_json(ld.SCHEMA_DIR / name)
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as e:
            fail(f"{name}: invalid schema: {e.message}")
            continue
        # Resolve every $def once so dangling cross-file refs surface here.
        for def_name in schema.get("$defs", {}):
            try:
                ld.validator_for(f"{name}#/$defs/{def_name}", reg).is_valid(None)
            except Exception as e:  # noqa: BLE001
                fail(f"{name}#/$defs/{def_name}: unresolvable: {e}")
        ok(f"schema {name} ({len(schema.get('$defs', {}))} definitions)")


def validate(def_ref: str, instance, label: str, reg) -> None:
    errs = ld.errors_for(def_ref, instance, reg)
    if errs:
        for e in errs[:10]:
            fail(f"{label}: {e}")
    else:
        ok(label)


def check_catalog(cat: Path, reg) -> None:
    entries = ld.read_catalog_entries(cat)
    for kind, items in entries.items():
        for item in items:
            validate(ld.DEF_FOR_KIND[kind], item, f"{cat}/{ld.CATALOG_KINDS[kind][0]}/{item[ld.CATALOG_KINDS[kind][1]]}", reg)
    manifest = ld.load_json(cat / "manifest.json")
    validate("i2-catalog.schema.json#/$defs/CatalogManifest", manifest, f"{cat}/manifest.json", reg)
    expected = ld.manifest_for(manifest.get("catalog_id", ""), entries)
    if manifest != expected:
        fail(f"{cat}/manifest.json does not match entry files; run tools/catalog.py seal")
    validate("i2-catalog.schema.json#/$defs/CatalogBundle", ld.bundle_for(cat), f"{cat} as CatalogBundle", reg)


def find_def(name: str) -> str | None:
    for f in ld.SCHEMA_FILES:
        if name in ld.load_json(ld.SCHEMA_DIR / f).get("$defs", {}):
            return f"{f}#/$defs/{name}"
    return None


def react_balance_failures(cat: Path) -> list[str]:
    """Return process ids whose REACT vectors do not balance every element, or whose
    PHASE joins species of different formulas."""
    entries = ld.read_catalog_entries(cat)
    formulas = {s["substance_id"]: s["formula"] for s in entries["substance"]}
    bad = []
    for proc in entries["process"]:
        for stage in proc["stages"]:
            for op in stage["ops"]:
                if op["op"] == "PHASE" and formulas[op["from"]] != formulas[op["to"]]:
                    bad.append(proc["process_id"])
                if op["op"] != "REACT":
                    continue
                totals: dict[str, Fraction] = {}
                for species, coeff in op["vector"].items():
                    for element, atoms in formulas[species].items():
                        totals[element] = totals.get(element, Fraction(0)) + int(coeff) * int(atoms)
                if any(v != 0 for v in totals.values()):
                    bad.append(proc["process_id"])
    return bad


def check_vector(d: Path, reg) -> None:
    manifest = ld.load_json(d / "vector.json")
    validate("i4-vectors.schema.json#/$defs/VectorManifest", manifest, f"{d}/vector.json", reg)
    if (d / "catalog").is_dir():
        check_catalog(d / "catalog", reg)
    if manifest.get("kind") == "ADMISSION":
        expected = ld.load_json(d / "expected/admission.json")
        validate("i4-vectors.schema.json#/$defs/ExpectedAdmission", expected, f"{d}/expected/admission.json", reg)
        if expected.get("verdict") == "ACCEPTED" or expected.get("failed_check") == "ELEMENT_BALANCE":
            bad = react_balance_failures(d / "catalog")
            agrees = (not bad) if expected["verdict"] == "ACCEPTED" else (expected.get("subject") in bad)
            (ok if agrees else fail)(f"{d}: expected verdict agrees with REACT balance sanity check")
    else:
        for line in ld.load_jsonl(d / "script.jsonl"):
            validate("i4-vectors.schema.json#/$defs/ScriptStep", line, f"{d}/script.jsonl", reg)
        for line in ld.load_jsonl(d / "commands.jsonl"):
            validate("i1-protocol.schema.json#/$defs/Command", line, f"{d}/commands.jsonl", reg)
        validate("i3-state.schema.json#/$defs/Genesis", ld.load_json(d / "genesis.json"), f"{d}/genesis.json", reg)
        exp = d / "expected"
        if exp.is_dir():
            validate("i4-vectors.schema.json#/$defs/ExpectedHashes", ld.load_json(exp / "hashes.json"), f"{d}/expected/hashes.json", reg)
            validate("i3-state.schema.json#/$defs/PhysicalState", ld.load_json(exp / "state.json"), f"{d}/expected/state.json", reg)
            for line in ld.load_jsonl(exp / "admissions.jsonl"):
                validate("i1-protocol.schema.json#/$defs/Admission", line, f"{d}/expected/admissions.jsonl", reg)
            for line in ld.load_jsonl(exp / "events.jsonl"):
                validate("i1-protocol.schema.json#/$defs/Event", line, f"{d}/expected/events.jsonl", reg)


def main() -> int:
    reg = ld.registry()
    check_schemas(reg)
    for cat in sorted((ld.ROOT / "examples/catalogs").iterdir()):
        check_catalog(cat, reg)
    validate("i3-state.schema.json#/$defs/Genesis", ld.load_json(ld.ROOT / "examples/genesis.json"), "examples/genesis.json", reg)
    for p in sorted((ld.ROOT / "examples/protocol").glob("*.json")):
        def_ref = find_def(p.stem)
        if not def_ref:
            fail(f"{p}: no definition named {p.stem}")
            continue
        validate(def_ref, ld.load_json(p), str(p.relative_to(ld.ROOT)), reg)
        # Every example must also be a valid envelope of its interface.
        envelope = "Request" if p.stem.endswith("Request") else "Response" if p.stem.endswith("Response") else None
        if envelope:
            validate(f"i1-protocol.schema.json#/$defs/{envelope}", ld.load_json(p), f"{p.name} as {envelope}", reg)
    for d in sorted((ld.ROOT / "vectors").iterdir()):
        if d.is_dir():
            check_vector(d, reg)
    print(f"\n{len(FAILURES)} failure(s)")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
