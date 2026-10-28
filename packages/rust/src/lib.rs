//! Types for the Lunar Dig interfaces I-1 to I-4 (LD-PEC-002).
//!
//! Everything in [`generated`] comes from `schemas/` via `tools/codegen.sh`. Do not edit it
//! by hand; change the schema and regenerate. Shape checks only: semantic rules such as
//! reduced rationals or element balance belong to the catalog validator and the vectors.

#[allow(clippy::all, missing_docs)]
pub mod generated;

pub use generated::*;
