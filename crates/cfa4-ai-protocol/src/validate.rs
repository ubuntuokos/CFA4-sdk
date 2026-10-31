// SPDX-License-Identifier: MIT OR Apache-2.0
//! The value constraints of `schemas/protocol.schema.json` that serde types
//! alone do not express (patterns, ranges, conditional fields).

use std::collections::HashSet;
use std::fmt;

use crate::message::{
    Buffer, BufferKind, Buffers, Caps, ErrorMessage, Hello, Load, Loaded, Message, Progress, Run,
    RunResult, Stats, Unload,
};

/// Largest integer every JSON implementation reads exactly (2^53 - 1).
pub const MAX_SAFE_INTEGER: u64 = 9_007_199_254_740_991;
/// Largest buffer the protocol describes (4 GiB).
pub const MAX_BUFFER_LEN: u64 = 1 << 32;
pub const MAX_DIMENSION: u32 = 16_384;
pub const MAX_FRAMES: u32 = 100_000;
pub const MAX_JOBS: u32 = 64;

/// A field that breaks the protocol schema.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ValidationError {
    /// Dotted path of the field, e.g. `run.inputs.src.width`.
    pub field: String,
    pub reason: &'static str,
}

impl fmt::Display for ValidationError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}: {}", self.field, self.reason)
    }
}

impl std::error::Error for ValidationError {}

type Check = Result<(), ValidationError>;

fn fail(field: impl Into<String>, reason: &'static str) -> Check {
    Err(ValidationError {
        field: field.into(),
        reason,
    })
}

fn safe_int(field: &str, v: u64) -> Check {
    if v > MAX_SAFE_INTEGER {
        fail(field, "larger than 2^53 - 1")
    } else {
        Ok(())
    }
}

fn range<T: PartialOrd>(field: &str, v: T, min: T, max: T, reason: &'static str) -> Check {
    if v < min || v > max {
        fail(field, reason)
    } else {
        Ok(())
    }
}

fn max_chars(field: &str, s: &str, max: usize) -> Check {
    if s.chars().count() > max {
        fail(field, "too long")
    } else {
        Ok(())
    }
}

fn is_lower_alnum(c: char) -> bool {
    c.is_ascii_lowercase() || c.is_ascii_digit()
}

/// `^[a-z0-9][a-z0-9-]{0,63}$`: implementation ids and worker names.
fn slug(field: &str, s: &str) -> Check {
    let mut chars = s.chars();
    let first_ok = chars.next().is_some_and(is_lower_alnum);
    if first_ok && s.len() <= 64 && chars.all(|c| is_lower_alnum(c) || c == '-') {
        Ok(())
    } else {
        fail(field, "must match ^[a-z0-9][a-z0-9-]{0,63}$")
    }
}

fn is_token_char(c: char) -> bool {
    c.is_ascii_alphanumeric() || c == '_' || c == '-'
}

/// `^[A-Za-z0-9_-]{1,64}$`: job ids and shared-memory name suffixes.
fn token(field: &str, s: &str) -> Check {
    if !s.is_empty() && s.len() <= 64 && s.chars().all(is_token_char) {
        Ok(())
    } else {
        fail(field, "must be 1-64 of A-Z a-z 0-9 _ -")
    }
}

/// `^[a-z][a-z0-9_]{0,31}$`: port names (buffer map keys).
fn port(field: &str, s: &str) -> Check {
    let mut chars = s.chars();
    let first_ok = chars.next().is_some_and(|c| c.is_ascii_lowercase());
    if first_ok && s.len() <= 32 && chars.all(|c| is_lower_alnum(c) || c == '_') {
        Ok(())
    } else {
        fail(field, "port name must match ^[a-z][a-z0-9_]{0,31}$")
    }
}

/// Shared-memory names the host may hand out.
pub const SHM_PREFIX: &str = "/cfa4-ai-";

fn buffer(field: &str, b: &Buffer) -> Check {
    match b.shm.strip_prefix(SHM_PREFIX) {
        Some(rest) => token(&format!("{field}.shm"), rest)?,
        None => return fail(format!("{field}.shm"), "must start with /cfa4-ai-"),
    }
    range(
        &format!("{field}.len"),
        b.len,
        1,
        MAX_BUFFER_LEN,
        "must be 1..=4 GiB",
    )?;
    if let Some(w) = b.width {
        range(
            &format!("{field}.width"),
            w,
            1,
            MAX_DIMENSION,
            "must be 1..=16384",
        )?;
    }
    if let Some(h) = b.height {
        range(
            &format!("{field}.height"),
            h,
            1,
            MAX_DIMENSION,
            "must be 1..=16384",
        )?;
    }
    if b.stride == Some(0) {
        return fail(format!("{field}.stride"), "must be at least 1");
    }
    if let Some(n) = b.frames {
        range(
            &format!("{field}.frames"),
            n,
            1,
            MAX_FRAMES,
            "must be 1..=100000",
        )?;
    }
    if matches!(b.kind, BufferKind::Frame | BufferKind::Mask) {
        let missing = [
            ("width", b.width.is_none()),
            ("height", b.height.is_none()),
            ("stride", b.stride.is_none()),
            ("format", b.format.is_none()),
        ];
        if let Some((name, _)) = missing.iter().find(|(_, absent)| *absent) {
            return fail(
                format!("{field}.{name}"),
                "required for frame and mask buffers",
            );
        }
    }
    Ok(())
}

fn buffers(field: &str, map: &Buffers) -> Check {
    for (name, b) in map {
        port(&format!("{field}.{name}"), name)?;
        buffer(&format!("{field}.{name}"), b)?;
    }
    Ok(())
}

fn hello(m: &Hello) -> Check {
    safe_int("hello.id", m.id)?;
    if m.protocol.min == 0 || m.protocol.max == 0 {
        return fail("hello.protocol", "versions start at 1");
    }
    max_chars("hello.host", &m.host, 120)
}

fn caps(m: &Caps) -> Check {
    safe_int("caps.id", m.id)?;
    safe_int("caps.reply_to", m.reply_to)?;
    if m.protocol == 0 {
        return fail("caps.protocol", "versions start at 1");
    }
    slug("caps.worker.name", &m.worker.name)?;
    max_chars("caps.worker.version", &m.worker.version, 64)?;
    let mut seen = HashSet::new();
    for i in &m.impls {
        slug("caps.impls", i)?;
        if !seen.insert(i) {
            return fail("caps.impls", "duplicate implementation");
        }
    }
    let l = &m.limits;
    range(
        "caps.limits.max_jobs",
        l.max_jobs,
        1,
        MAX_JOBS,
        "must be 1..=64",
    )?;
    if l.max_buffer_bytes == Some(0) {
        return fail("caps.limits.max_buffer_bytes", "must be at least 1");
    }
    if let Some(d) = l.max_duration_s {
        if !(d.is_finite() && d > 0.0) {
            return fail("caps.limits.max_duration_s", "must be a positive number");
        }
    }
    if l.max_output_height == Some(0) {
        return fail("caps.limits.max_output_height", "must be at least 1");
    }
    if l.watermark_above_height == Some(0) {
        return fail("caps.limits.watermark_above_height", "must be at least 1");
    }
    if let Some(devices) = &m.devices {
        let mut seen = HashSet::new();
        if !devices.iter().all(|d| seen.insert(*d)) {
            return fail("caps.devices", "duplicate device");
        }
    }
    if let Some(features) = &m.features {
        let mut seen = HashSet::new();
        if !features.iter().all(|f| seen.insert(*f)) {
            return fail("caps.features", "duplicate feature");
        }
    }
    if let Some(i) = &m.post_export {
        slug("caps.post_export", i)?;
    }
    if m.protocol == 1 {
        if m.features.is_some() {
            return fail("caps.features", "not in protocol version 1");
        }
        if m.post_export.is_some() {
            return fail("caps.post_export", "not in protocol version 1");
        }
        if l.watermark_above_height.is_some() {
            return fail(
                "caps.limits.watermark_above_height",
                "not in protocol version 1",
            );
        }
    }
    Ok(())
}

fn load(m: &Load) -> Check {
    safe_int("load.id", m.id)?;
    slug("load.impl", &m.implementation)?;
    match &m.weights_dir {
        Some(dir) if !dir.starts_with('/') => fail("load.weights_dir", "must be an absolute path"),
        _ => Ok(()),
    }
}

fn loaded(m: &Loaded) -> Check {
    safe_int("loaded.id", m.id)?;
    safe_int("loaded.reply_to", m.reply_to)?;
    slug("loaded.impl", &m.implementation)
}

fn run(m: &Run) -> Check {
    safe_int("run.id", m.id)?;
    token("run.job", &m.job)?;
    slug("run.impl", &m.implementation)?;
    buffers("run.inputs", &m.inputs)?;
    buffers("run.outputs", &m.outputs)?;
    if let Some(seed) = m.seed {
        safe_int("run.seed", seed)?;
    }
    if let Some(r) = m.range {
        range(
            "run.range.count",
            r.count,
            1,
            MAX_FRAMES,
            "must be 1..=100000",
        )?;
    }
    if let Some(c) = m.chunk {
        if c.count == 0 {
            return fail("run.chunk.count", "must be at least 1");
        }
    }
    Ok(())
}

fn progress(m: &Progress) -> Check {
    safe_int("progress.id", m.id)?;
    safe_int("progress.reply_to", m.reply_to)?;
    token("progress.job", &m.job)?;
    if m.total == 0 {
        return fail("progress.total", "must be at least 1");
    }
    match &m.stage {
        Some(stage) => max_chars("progress.stage", stage, 64),
        None => Ok(()),
    }
}

fn result(m: &RunResult) -> Check {
    safe_int("result.id", m.id)?;
    safe_int("result.reply_to", m.reply_to)?;
    token("result.job", &m.job)?;
    buffers("result.outputs", &m.outputs)
}

fn unload(m: &Unload) -> Check {
    safe_int("unload.id", m.id)?;
    slug("unload.impl", &m.implementation)
}

fn stats(m: &Stats) -> Check {
    safe_int("stats.id", m.id)?;
    if let Some(r) = m.reply_to {
        safe_int("stats.reply_to", r)?;
    }
    for r in &m.loaded {
        slug("stats.loaded.impl", &r.implementation)?;
    }
    Ok(())
}

fn error(m: &ErrorMessage) -> Check {
    safe_int("error.id", m.id)?;
    if let Some(r) = m.reply_to {
        safe_int("error.reply_to", r)?;
    }
    if let Some(job) = &m.job {
        token("error.job", job)?;
    }
    max_chars("error.message", &m.message, 2000)
}

/// Checks every constraint of the schema that the types do not enforce.
pub fn validate(message: &Message) -> Result<(), ValidationError> {
    match message {
        Message::Hello(m) => hello(m),
        Message::Caps(m) => caps(m),
        Message::Load(m) => load(m),
        Message::Loaded(m) => loaded(m),
        Message::Run(m) => run(m),
        Message::Progress(m) => progress(m),
        Message::Result(m) => result(m),
        Message::Cancel(m) => {
            safe_int("cancel.id", m.id)?;
            token("cancel.job", &m.job)
        }
        Message::Unload(m) => unload(m),
        Message::Stats(m) => stats(m),
        Message::Error(m) => error(m),
        Message::Shutdown(m) => safe_int("shutdown.id", m.id),
    }
}

impl Buffer {
    /// Whether the buffer lies inside a shared-memory segment of
    /// `segment_len` bytes. The host checks this before mapping.
    pub fn fits(&self, segment_len: u64) -> bool {
        self.offset
            .checked_add(self.len)
            .is_some_and(|end| end <= segment_len)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::codec::decode;

    fn frame(extra: &str) -> String {
        format!(
            r#"{{"type":"run","id":1,"job":"j","impl":"x","device":0,"inputs":{{"src":{{"shm":"/cfa4-ai-a","offset":0,"len":12,"kind":"frame"{extra}}}}},"outputs":{{}},"params":{{}},"tier":"final"}}"#
        )
    }

    fn field_of(line: &str) -> String {
        match decode(line.as_bytes()) {
            Err(crate::ProtocolError::Invalid(e)) => e.field,
            other => panic!("expected a validation error, got {other:?}"),
        }
    }

    #[test]
    fn frame_buffers_need_geometry_and_format() {
        assert_eq!(field_of(&frame("")), "run.inputs.src.width");
        assert_eq!(
            field_of(&frame(r#","width":2,"height":2,"stride":6"#)),
            "run.inputs.src.format"
        );
        assert!(
            decode(frame(r#","width":2,"height":2,"stride":6,"format":"rgb8""#).as_bytes()).is_ok()
        );
    }

    #[test]
    fn dimensions_are_bounded() {
        assert_eq!(
            field_of(&frame(
                r#","width":16385,"height":2,"stride":6,"format":"rgb8""#
            )),
            "run.inputs.src.width"
        );
        assert_eq!(
            field_of(&frame(
                r#","width":2,"height":0,"stride":6,"format":"rgb8""#
            )),
            "run.inputs.src.height"
        );
    }

    #[test]
    fn shared_memory_names_are_confined() {
        let run = frame(r#","width":2,"height":2,"stride":6,"format":"rgb8""#);
        for bad in ["/tmp/x", "/cfa4-ai-", "/cfa4-ai-../x", "cfa4-ai-a"] {
            let line = run.replace("/cfa4-ai-a", bad);
            assert_eq!(field_of(&line), "run.inputs.src.shm", "{bad}");
        }
    }

    #[test]
    fn port_names_and_ids_follow_their_patterns() {
        let run = frame(r#","width":2,"height":2,"stride":6,"format":"rgb8""#);
        assert_eq!(
            field_of(&run.replace("\"src\"", "\"Src\"")),
            "run.inputs.Src"
        );
        assert_eq!(
            field_of(&run.replace("\"impl\":\"x\"", "\"impl\":\"-x\"")),
            "run.impl"
        );
        assert_eq!(
            field_of(&run.replace("\"job\":\"j\"", "\"job\":\"j k\"")),
            "run.job"
        );
    }

    #[test]
    fn caps_limits_and_duplicates() {
        let caps = r#"{"type":"caps","id":0,"reply_to":0,"protocol":1,"worker":{"name":"w","version":"1"},"impls":["a"],"limits":{"max_jobs":1}}"#;
        assert!(decode(caps.as_bytes()).is_ok());
        assert_eq!(
            field_of(&caps.replace("[\"a\"]", "[\"a\",\"a\"]")),
            "caps.impls"
        );
        assert_eq!(
            field_of(&caps.replace("\"max_jobs\":1", "\"max_jobs\":65")),
            "caps.limits.max_jobs"
        );
        assert_eq!(
            field_of(&caps.replace("\"max_jobs\":1", "\"max_jobs\":1,\"max_duration_s\":0")),
            "caps.limits.max_duration_s"
        );
        assert_eq!(
            field_of(&caps.replace("}}", "},\"devices\":[0,0]}")),
            "caps.devices"
        );
    }

    #[test]
    fn caps_version_2_fields() {
        let v2 = r#"{"type":"caps","id":0,"reply_to":0,"protocol":2,"worker":{"name":"w","version":"1"},"impls":["a","wm"],"limits":{"max_jobs":1,"watermark_above_height":1080},"features":["cancel","resume"],"post_export":"wm"}"#;
        assert!(decode(v2.as_bytes()).is_ok());
        assert_eq!(
            field_of(&v2.replace("\"cancel\",\"resume\"", "\"cancel\",\"cancel\"")),
            "caps.features"
        );
        assert_eq!(
            field_of(&v2.replace("1080", "0")),
            "caps.limits.watermark_above_height"
        );
        assert_eq!(
            field_of(&v2.replace("\"post_export\":\"wm\"", "\"post_export\":\"Wm\"")),
            "caps.post_export"
        );
        assert!(decode(v2.replace("\"resume\"", "\"teleport\"").as_bytes()).is_err());
        let v1 = v2.replace("\"protocol\":2", "\"protocol\":1");
        assert_eq!(field_of(&v1), "caps.features");
        let v1 = v1.replace(",\"features\":[\"cancel\",\"resume\"]", "");
        assert_eq!(field_of(&v1), "caps.post_export");
        let v1 = v1.replace(",\"post_export\":\"wm\"", "");
        assert_eq!(field_of(&v1), "caps.limits.watermark_above_height");
        let v1 = v1.replace(",\"watermark_above_height\":1080", "");
        assert!(decode(v1.as_bytes()).is_ok());
    }

    #[test]
    fn buffer_fits_checks_overflow() {
        let b = Buffer {
            shm: "/cfa4-ai-a".into(),
            offset: u64::MAX,
            len: 2,
            kind: BufferKind::Tensor,
            width: None,
            height: None,
            stride: None,
            frames: None,
            format: None,
            color: None,
            premultiplied: None,
        };
        assert!(!b.fits(u64::MAX));
        let b = Buffer { offset: 10, ..b };
        assert!(b.fits(12));
        assert!(!b.fits(11));
    }
}
