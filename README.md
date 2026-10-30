# ld-interfaces

The four interfaces that let Lunar Dig's alpha workstreams build in parallel, as JSON Schema (LD-PEC-002). Every other repository depends on this one; none depends on another's internals.

| Interface | Schema | Defines | Owner |
| --- | --- | --- | --- |
| I-1 SDK protocol | `schemas/i1-protocol.schema.json` | Requests and responses, commands, observations, events, errors | W2 |
| I-2 Catalog | `schemas/i2-catalog.schema.json` | Elements, units, substances, processes (primitive set v0), blueprints, manifests | W2 with W4 |
| I-3 State | `schemas/i3-state.schema.json` | Genesis, physical state, snapshots, history records | W1 |
| I-4 Vectors | `schemas/i4-vectors.schema.json` | Conformance vector layout and expected results | W2 with W5 |

Shared scalars (decimal-string integers, rationals, ids, hashes) are in `schemas/common.schema.json`.

**Status:** v0 draft. Nothing here is stable until the M0 freeze (see `CONTRIBUTING.md`). The numeric profile is provisional until O-10 closes.

## Layout

```text
schemas/      JSON Schema 2020-12, the single source of truth
examples/     A sealed sample catalog, a genesis, and one example per protocol message
vectors/      Conformance vectors (I-4); all currently DRAFT
bundle/       Generated: every schema merged into one document for code generators
packages/
  rust/       Generated Rust types (crate ld-interfaces-types) plus round-trip tests
  ts/         Generated TypeScript types (@lunardig/ld-interfaces)
tools/        check.py, catalog.py, bundle.py, codegen.sh
```

## Using it

```sh
pip install -r requirements.txt
python tools/check.py                    # validate schemas, examples, vectors, manifests
./tools/codegen.sh                       # regenerate bundle, Rust and TypeScript types
python tools/catalog.py bundle examples/catalogs/electrolysis   # CatalogBundle for I-1 create
```

`codegen.sh` needs Node 22 and `cargo install cargo-typify --version 0.8.0 --locked`.

## Conventions worth knowing

- **No JSON numbers anywhere.** Integers are canonical decimal strings, rationals are `{"n": "...", "d": "..."}`. The UI may convert to floats for display, never for anything it sends back.
- **Tagged unions.** Commands are tagged by `op`, requests and responses by `method` (failures use `"method": "error"`), events by `kind`, stall reasons by `code`, expressions by `kind`.
- **Hashing.** `H(domain, payload) = SHA256(UTF8(domain) || 0x00 || uint64_be(len) || payload)` over the canonical (JCS) bytes. Catalog entries use domain `ld.<kind>.v0` (for example `ld.process.v0`); the manifest uses `ld.catalog.v0`, and its hash is the catalog hash. Reference code: `tools/ld.py`.
- **Schemas check shape only.** Reduced rationals, sorted collections, existing references and element balance are the catalog validator's and the vectors' job. `tools/check.py` includes a REACT balance sanity check so the sample vectors cannot drift, but it is not the validator.

## Specifications

LD-PEC-001 (physical contract), LD-PEC-002 (this interface set) and LD-PEC-003 (primitive set) live in the `lunardig/architecture` repository.

## License

Apache License 2.0 (LICENSE, NOTICE), as drafted for review. When the repository becomes public is still open question Q-07 in LD-PEC-002.
