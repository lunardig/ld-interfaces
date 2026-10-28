//! Every protocol example in examples/protocol must deserialize into the generated
//! Request or Response type and serialize back to the same JSON value.

use std::fs;
use std::path::PathBuf;

use ld_interfaces_types::{Request, Response};

fn examples() -> Vec<PathBuf> {
    let dir = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../examples/protocol");
    let mut paths: Vec<_> = fs::read_dir(dir).unwrap().map(|e| e.unwrap().path()).collect();
    paths.sort();
    assert!(!paths.is_empty(), "no protocol examples found");
    paths
}

#[test]
fn protocol_examples_round_trip() {
    for path in examples() {
        let text = fs::read_to_string(&path).unwrap();
        let original: serde_json::Value = serde_json::from_str(&text).unwrap();
        let stem = path.file_stem().unwrap().to_string_lossy();
        let reencoded = if stem.ends_with("Request") {
            let typed: Request = serde_json::from_str(&text)
                .unwrap_or_else(|e| panic!("{}: {e}", path.display()));
            serde_json::to_value(&typed).unwrap()
        } else {
            let typed: Response = serde_json::from_str(&text)
                .unwrap_or_else(|e| panic!("{}: {e}", path.display()));
            serde_json::to_value(&typed).unwrap()
        };
        assert_eq!(original, reencoded, "{} did not round-trip", path.display());
    }
}

#[test]
fn identically_shaped_variants_stay_distinct() {
    // STARVED_POWER and DWELLING have the same shape; the tag alone must decide.
    let r: ld_interfaces_types::Reason = serde_json::from_str(r#"{"code":"DWELLING"}"#).unwrap();
    assert!(matches!(r, ld_interfaces_types::Reason::Dwelling));
}

#[test]
fn json_numbers_are_rejected() {
    let bad = r#"{"id":"1","method":"advance_to","params":{"t_us":86400}}"#;
    assert!(serde_json::from_str::<Request>(bad).is_err());
}
