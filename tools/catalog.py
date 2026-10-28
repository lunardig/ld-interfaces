"""Catalog utilities.

  python tools/catalog.py seal   <catalog-dir> --id <catalog_id>   write manifest.json from entry files
  python tools/catalog.py hash   <catalog-dir>                     print the catalog hash
  python tools/catalog.py bundle <catalog-dir>                     print the CatalogBundle used by I-1 create
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ld  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=["seal", "hash", "bundle"])
    p.add_argument("catalog_dir", type=Path)
    p.add_argument("--id", dest="catalog_id")
    a = p.parse_args()

    if a.command == "seal":
        if not a.catalog_id:
            p.error("seal requires --id")
        manifest = ld.manifest_for(a.catalog_id, ld.read_catalog_entries(a.catalog_dir))
        (a.catalog_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(ld.catalog_hash(manifest))
    elif a.command == "hash":
        print(ld.catalog_hash(ld.load_json(a.catalog_dir / "manifest.json")))
    else:
        print(json.dumps(ld.bundle_for(a.catalog_dir), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
