// SPDX-License-Identifier: MIT OR Apache-2.0
//! The crate against the shared examples: every valid line round-trips
//! unchanged, every invalid line is rejected.
#![allow(clippy::panic, clippy::unwrap_used)]

use std::fs;
use std::path::PathBuf;

use cfa4_ai_protocol::{MessageReader, decode, encode};

fn example(name: &str) -> String {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../examples/messages")
        .join(name);
    fs::read_to_string(&path).unwrap_or_else(|e| panic!("{}: {e}", path.display()))
}

fn lines(name: &str) -> Vec<String> {
    example(name)
        .lines()
        .filter(|l| !l.trim().is_empty())
        .map(str::to_owned)
        .collect()
}

#[test]
fn valid_examples_round_trip_unchanged() {
    for file in ["session.jsonl", "full.jsonl"] {
        for (n, line) in lines(file).iter().enumerate() {
            let message =
                decode(line.as_bytes()).unwrap_or_else(|e| panic!("{file}:{}: {e}", n + 1));
            let encoded = encode(&message).unwrap_or_else(|e| panic!("{file}:{}: {e}", n + 1));
            let before: serde_json::Value = serde_json::from_str(line).unwrap();
            let after: serde_json::Value = serde_json::from_slice(&encoded).unwrap();
            assert_eq!(before, after, "{file}:{}", n + 1);
        }
    }
}

#[test]
fn invalid_examples_are_rejected() {
    for (n, line) in lines("invalid.jsonl").iter().enumerate() {
        assert!(
            decode(line.as_bytes()).is_err(),
            "invalid.jsonl:{} was accepted: {line}",
            n + 1
        );
    }
}

#[test]
fn reader_reads_the_whole_session() {
    let text = example("session.jsonl");
    let mut reader = MessageReader::new(text.as_bytes());
    let mut kinds = Vec::new();
    while let Some(message) = reader.next_message().unwrap() {
        kinds.push(message.kind());
    }
    assert_eq!(kinds.first(), Some(&"hello"));
    assert_eq!(kinds.last(), Some(&"shutdown"));
    assert_eq!(kinds.len(), lines("session.jsonl").len());
}
