// SPDX-License-Identifier: MIT OR Apache-2.0
//! The CFA4 AI worker protocol, version 2 (version 1 still accepted): message
//! types, validation and JSON-lines framing. The normative description is
//! `docs/protocol.md` and `schemas/protocol.schema.json` in the CFA4-sdk
//! repository; this crate accepts exactly what that schema accepts.
//!
//! The crate does no I/O of its own beyond reading and writing lines on a
//! stream the caller opened (a Unix socket in CFA4), and it does not map
//! shared memory: [`Buffer::fits`] is the bounds check a mapper needs.

mod codec;
mod message;
mod validate;

pub use codec::{MAX_LINE_BYTES, MessageReader, ProtocolError, decode, encode, write_message};
pub use message::*;
pub use validate::{
    MAX_BUFFER_LEN, MAX_DIMENSION, MAX_FRAMES, MAX_JOBS, MAX_SAFE_INTEGER, SHM_PREFIX,
    ValidationError, validate,
};

/// The newest protocol version this crate implements.
pub const PROTOCOL_VERSION: u32 = 2;

/// The oldest protocol version this crate still accepts.
pub const MIN_PROTOCOL_VERSION: u32 = 1;

/// Environment variable through which the host passes the socket path.
pub const SOCKET_ENV: &str = "CFA4_AI_SOCKET";

/// The version both sides speak: the highest version in the host's range
/// that the worker also supports (`worker_min..=worker_max`), if any.
pub fn negotiate(host: VersionRange, worker_min: u32, worker_max: u32) -> Option<u32> {
    let low = host.min.max(worker_min).max(1);
    let high = host.max.min(worker_max);
    (low <= high).then_some(high)
}

/// Whether the version a worker chose in [`Caps`] is one the host offered.
pub fn accepts(host: VersionRange, chosen: u32) -> bool {
    chosen >= 1 && host.min <= chosen && chosen <= host.max
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn negotiation_picks_the_highest_common_version() {
        let host = VersionRange { min: 1, max: 3 };
        assert_eq!(negotiate(host, 1, 1), Some(1));
        assert_eq!(negotiate(host, 2, 5), Some(3));
        assert_eq!(negotiate(host, 4, 5), None);
        assert_eq!(negotiate(VersionRange { min: 0, max: 0 }, 0, 1), None);
        assert!(accepts(host, 2));
        assert!(!accepts(host, 4));
        assert!(!accepts(VersionRange { min: 0, max: 1 }, 0));
    }
}
