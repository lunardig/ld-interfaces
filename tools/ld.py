"""Shared helpers for ld-interfaces tooling: canonical JSON, domain-separated hashing,
schema loading and catalog handling. Standard library plus `jsonschema` only."""
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = ROOT / "schemas"
SCHEMA_FILES = [
    "common.schema.json",
    "i1-protocol.schema.json",
    "i2-catalog.schema.json",
    "i3-state.schema.json",
    "i4-vectors.schema.json",
]
BASE_URI = "https://github.com/lunardig/ld-interfaces/schemas/v0/"

# Catalog entry kind -> (directory name, id field, bundle key)
CATALOG_KINDS = {
    "element": ("elements", "element_id", "elements"),
    "unit": ("units", "unit_id", "units"),
    "substance": ("substances", "substance_id", "substances"),
    "process": ("processes", "process_id", "processes"),
    "machine": ("machines", "blueprint_id", "machines"),
    "product": ("products", "product_id", "products"),
    "buffer": ("buffers", "template_id", "buffers"),
    "environment": ("environment", "function_id", "environment"),
}
DEF_FOR_KIND = {
    "element": "i2-catalog.schema.json#/$defs/Element",
    "unit": "i2-catalog.schema.json#/$defs/Unit",
    "substance": "i2-catalog.schema.json#/$defs/Substance",
    "process": "i2-catalog.schema.json#/$defs/Process",
    "machine": "i2-catalog.schema.json#/$defs/MachineBlueprint",
    "product": "i2-catalog.schema.json#/$defs/ProductBlueprint",
    "buffer": "i2-catalog.schema.json#/$defs/BufferTemplate",
    "environment": "i2-catalog.schema.json#/$defs/EnvironmentFunction",
}


# ---------------------------------------------------------------- canonical form
def canonical_bytes(value) -> bytes:
    """JCS (RFC 8785) for the LD-PEC-002 profile.

    The profile forbids JSON numbers, so JCS number serialization never arises. Object keys
    are ASCII identifiers, so code-point order equals JCS's UTF-16 order. Free-text values
    are escaped exactly as ECMAScript JSON.stringify does for the characters JSON requires.
    """
    _reject_numbers(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _reject_numbers(value, path="$"):
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return
    if isinstance(value, (int, float)):
        raise ValueError(f"JSON number at {path}; the profile requires decimal strings")
    if isinstance(value, list):
        for i, v in enumerate(value):
            _reject_numbers(v, f"{path}[{i}]")
    elif isinstance(value, dict):
        for k, v in value.items():
            _reject_numbers(v, f"{path}.{k}")


def domain_hash(domain: str, payload: bytes) -> str:
    """H(domain, payload) = SHA256(UTF8(domain) || 0x00 || uint64_be(len(payload)) || payload)."""
    h = hashlib.sha256()
    h.update(domain.encode("utf-8") + b"\x00" + struct.pack(">Q", len(payload)) + payload)
    return h.hexdigest()


def entry_domain(kind: str) -> str:
    return f"ld.{kind}.v0"


def hash_value(domain: str, value) -> str:
    return domain_hash(domain, canonical_bytes(value))


# ---------------------------------------------------------------- schemas
def load_json(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_jsonl(path: Path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def registry():
    from referencing import Registry, Resource

    resources = []
    for name in SCHEMA_FILES:
        resources.append((BASE_URI + name, Resource.from_contents(load_json(SCHEMA_DIR / name))))
    return Registry().with_resources(resources)


def validator_for(def_ref: str, reg=None):
    """Validator for one definition, e.g. 'i2-catalog.schema.json#/$defs/Process'."""
    from jsonschema import Draft202012Validator

    reg = reg or registry()
    return Draft202012Validator({"$ref": BASE_URI + def_ref}, registry=reg)


def errors_for(def_ref: str, instance, reg=None) -> list[str]:
    from jsonschema.exceptions import best_match

    v = validator_for(def_ref, reg)
    out = []
    for e in sorted(v.iter_errors(instance), key=lambda e: list(e.absolute_path)):
        # For oneOf failures, report the closest branch's error instead of the whole instance.
        while e.context:
            e = best_match(e.context)
        loc = "/".join(str(p) for p in e.absolute_path) or "(root)"
        msg = e.message if len(e.message) <= 200 else e.message[:200] + "..."
        out.append(f"{loc}: {msg}")
    return out


# ---------------------------------------------------------------- catalogs
def read_catalog_entries(catalog_dir: Path) -> dict[str, list[dict]]:
    """Read entry files from <catalog>/<kind dir>/*.json."""
    entries = {}
    for kind, (dirname, id_field, _) in CATALOG_KINDS.items():
        items = []
        d = catalog_dir / dirname
        if d.is_dir():
            for p in sorted(d.glob("*.json")):
                item = load_json(p)
                if item.get(id_field) != p.stem:
                    raise ValueError(f"{p}: file name must equal {id_field} ({item.get(id_field)!r})")
                items.append(item)
        entries[kind] = items
    return entries


def manifest_for(catalog_id: str, entries: dict[str, list[dict]]) -> dict:
    rows = []
    for kind, items in entries.items():
        id_field = CATALOG_KINDS[kind][1]
        for item in items:
            rows.append({"kind": kind, "id": item[id_field], "hash": hash_value(entry_domain(kind), item)})
    rows.sort(key=lambda r: (r["kind"], r["id"]))
    return {"schema": "ld.catalog.v0", "catalog_id": catalog_id, "pset_version": "0", "entries": rows}


def catalog_hash(manifest: dict) -> str:
    return hash_value("ld.catalog.v0", manifest)


def bundle_for(catalog_dir: Path) -> dict:
    manifest = load_json(catalog_dir / "manifest.json")
    entries = read_catalog_entries(catalog_dir)
    bundle = {"manifest": manifest}
    for kind, (_, _, key) in CATALOG_KINDS.items():
        bundle[key] = entries[kind]
    return bundle
