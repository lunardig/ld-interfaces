# Changing an interface

These schemas are the contract between the alpha workstreams (LD-PEC-002 §8).

| Phase | Rule |
| --- | --- |
| Before M0 | v0 drafts. Interface owners change them freely; consumers review. |
| M0 freeze | I-1 and I-2 frozen at v1 so the web UI (W3) and starter catalog (W4) can build. I-3 and I-4 may change until M1. |
| After freeze | Additive changes (new optional fields, new commands, new reason codes) bump the minor version. Anything else is breaking. |
| Breaking change | A pull request approved by the interface owner and every consuming workstream, carrying updated schemas, examples, vectors and the mock engine together. |

Owners: I-1 and I-2 W2 (with W4 for I-2), I-3 W1, I-4 W2 with W5.

## Every change

1. Edit `schemas/`. Never edit `bundle/` or any `generated` file; they are rebuilt from the schemas.
2. Update or add examples in `examples/` and vectors in `vectors/`.
3. If you touched a catalog, reseal it: `python tools/catalog.py seal <dir> --id <catalog_id>`.
4. Run `python tools/check.py` and `./tools/codegen.sh`, then commit the regenerated files.

## Schema style

Code generators read these schemas, so keep to a style they handle well:

- Unions are `oneOf` lists of `$ref`s to object definitions that share one `const` discriminator (`op`, `kind`, `code`, `method`, `step`). The bundler inlines them so generators emit tagged enums.
- Give every object nested inside a union variant its own named definition. Anonymous nested objects get merged by name in generated code.
- No `allOf` or `anyOf`. No JSON numbers: integers and rationals are decimal strings.
- Definition names are unique across all schema files.
