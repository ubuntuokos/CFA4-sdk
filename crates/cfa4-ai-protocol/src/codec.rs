// SPDX-License-Identifier: MIT OR Apache-2.0
//! JSON-lines framing: one UTF-8 JSON object per line, at most
//! [`MAX_LINE_BYTES`] bytes including the newline.

use std::fmt;
use std::io::{self, BufRead, Read, Write};

use crate::message::Message;
use crate::validate::{ValidationError, validate};

/// Longest line either side may send, newline included (1 MiB).
pub const MAX_LINE_BYTES: usize = 1 << 20;

#[derive(Debug)]
pub enum ProtocolError {
    Io(io::Error),
    /// The line is longer than [`MAX_LINE_BYTES`]. The connection must be
    /// closed: the reader stops at the limit and cannot resynchronize.
    LineTooLong,
    /// The stream ended in the middle of a line.
    Truncated,
    /// Not JSON, or JSON that does not match any message type.
    Json(serde_json::Error),
    Invalid(ValidationError),
}

impl fmt::Display for ProtocolError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Io(e) => write!(f, "i/o error: {e}"),
            Self::LineTooLong => write!(f, "line longer than {MAX_LINE_BYTES} bytes"),
            Self::Truncated => write!(f, "stream ended inside a line"),
            Self::Json(e) => write!(f, "malformed message: {e}"),
            Self::Invalid(e) => write!(f, "invalid message: {e}"),
        }
    }
}

impl std::error::Error for ProtocolError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            Self::Io(e) => Some(e),
            Self::Json(e) => Some(e),
            Self::Invalid(e) => Some(e),
            Self::LineTooLong | Self::Truncated => None,
        }
    }
}

impl From<io::Error> for ProtocolError {
    fn from(e: io::Error) -> Self {
        Self::Io(e)
    }
}

impl From<ValidationError> for ProtocolError {
    fn from(e: ValidationError) -> Self {
        Self::Invalid(e)
    }
}

/// Parses and validates one line (with or without its trailing newline).
pub fn decode(line: &[u8]) -> Result<Message, ProtocolError> {
    let line = line.strip_suffix(b"\n").unwrap_or(line);
    if line.len() >= MAX_LINE_BYTES {
        return Err(ProtocolError::LineTooLong);
    }
    let message: Message = serde_json::from_slice(line).map_err(ProtocolError::Json)?;
    validate(&message)?;
    Ok(message)
}

/// Validates and serializes one message as a line ending in `\n`.
pub fn encode(message: &Message) -> Result<Vec<u8>, ProtocolError> {
    validate(message)?;
    let mut line = serde_json::to_vec(message).map_err(ProtocolError::Json)?;
    line.push(b'\n');
    if line.len() > MAX_LINE_BYTES {
        return Err(ProtocolError::LineTooLong);
    }
    Ok(line)
}

/// Writes one message and flushes it.
pub fn write_message<W: Write>(writer: &mut W, message: &Message) -> Result<(), ProtocolError> {
    writer.write_all(&encode(message)?)?;
    writer.flush()?;
    Ok(())
}

/// Reads messages line by line, never buffering more than one line.
pub struct MessageReader<R> {
    inner: R,
    line: Vec<u8>,
}

impl<R: BufRead> MessageReader<R> {
    pub fn new(inner: R) -> Self {
        Self {
            inner,
            line: Vec::new(),
        }
    }

    /// The next message, or `None` at a clean end of stream. Blank lines are
    /// skipped. After [`ProtocolError::LineTooLong`] the caller must close
    /// the connection.
    pub fn next_message(&mut self) -> Result<Option<Message>, ProtocolError> {
        loop {
            self.line.clear();
            let limit = u64::try_from(MAX_LINE_BYTES).unwrap_or(u64::MAX);
            let n = (&mut self.inner)
                .take(limit)
                .read_until(b'\n', &mut self.line)?;
            if n == 0 {
                return Ok(None);
            }
            if self.line.last() != Some(&b'\n') {
                return Err(if n >= MAX_LINE_BYTES {
                    ProtocolError::LineTooLong
                } else {
                    ProtocolError::Truncated
                });
            }
            if self.line.iter().all(|b| b.is_ascii_whitespace()) {
                continue;
            }
            return decode(&self.line).map(Some);
        }
    }

    pub fn into_inner(self) -> R {
        self.inner
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::message::{Device, Message, Shutdown};

    fn shutdown(id: u64) -> Message {
        Message::Shutdown(Shutdown { id })
    }

    #[test]
    fn encode_appends_one_newline() {
        let line = encode(&shutdown(7)).unwrap();
        assert_eq!(line, b"{\"type\":\"shutdown\",\"id\":7}\n");
    }

    #[test]
    fn encode_refuses_invalid_messages() {
        assert!(matches!(
            encode(&shutdown(1 << 53)),
            Err(ProtocolError::Invalid(_))
        ));
    }

    #[test]
    fn reader_skips_blank_lines_and_stops_at_eof() {
        let mut reader = MessageReader::new(&b"\n{\"type\":\"shutdown\",\"id\":1}\n  \n"[..]);
        assert_eq!(reader.next_message().unwrap(), Some(shutdown(1)));
        assert_eq!(reader.next_message().unwrap(), None);
    }

    #[test]
    fn reader_reports_a_truncated_last_line() {
        let mut reader = MessageReader::new(&b"{\"type\":\"shutdown\",\"id\":1}"[..]);
        assert!(matches!(
            reader.next_message(),
            Err(ProtocolError::Truncated)
        ));
    }

    #[test]
    fn reader_stops_at_the_line_limit() {
        let mut long = vec![b' '; MAX_LINE_BYTES + 10];
        long.push(b'\n');
        let mut reader = MessageReader::new(&long[..]);
        assert!(matches!(
            reader.next_message(),
            Err(ProtocolError::LineTooLong)
        ));
    }

    #[test]
    fn a_line_of_exactly_the_limit_is_accepted() {
        let body = b"{\"type\":\"shutdown\",\"id\":1}";
        let mut line = body.to_vec();
        line.resize(MAX_LINE_BYTES - 1, b' ');
        line.push(b'\n');
        let mut reader = MessageReader::new(&line[..]);
        assert_eq!(reader.next_message().unwrap(), Some(shutdown(1)));
    }

    #[test]
    fn unknown_fields_and_types_are_rejected() {
        assert!(matches!(
            decode(br#"{"type":"shutdown","id":1,"x":0}"#),
            Err(ProtocolError::Json(_))
        ));
        assert!(matches!(
            decode(br#"{"type":"teleport","id":1}"#),
            Err(ProtocolError::Json(_))
        ));
        assert!(matches!(decode(b"not json"), Err(ProtocolError::Json(_))));
    }

    #[test]
    fn devices_are_cpu_or_a_bounded_gpu_index() {
        let parse = |s: &str| serde_json::from_str::<Device>(s);
        assert_eq!(parse("\"cpu\"").unwrap(), Device::Cpu);
        assert_eq!(parse("63").unwrap(), Device::Gpu(63));
        for bad in ["64", "-1", "\"gpu\"", "1.5", "null"] {
            assert!(parse(bad).is_err(), "{bad} accepted");
        }
        assert_eq!(serde_json::to_string(&Device::Gpu(2)).unwrap(), "2");
        assert_eq!(serde_json::to_string(&Device::Cpu).unwrap(), "\"cpu\"");
    }
}
