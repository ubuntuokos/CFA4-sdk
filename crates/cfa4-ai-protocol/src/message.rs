// SPDX-License-Identifier: MIT OR Apache-2.0
//! Message types, one per `$defs` entry of `schemas/protocol.schema.json`.

use std::collections::BTreeMap;
use std::fmt;

use serde::de::{self, Visitor};
use serde::{Deserialize, Deserializer, Serialize, Serializer};

/// JSON object of implementation parameters, validated by the host against
/// the manifest's params schema.
pub type Params = serde_json::Map<String, serde_json::Value>;

/// Named buffers of a run, keyed by port name (`src`, `mask`, `out`, ...).
pub type Buffers = BTreeMap<String, Buffer>;

/// One protocol message. The JSON `type` field selects the variant.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum Message {
    Hello(Hello),
    Caps(Caps),
    Load(Load),
    Loaded(Loaded),
    Run(Run),
    Progress(Progress),
    Result(RunResult),
    Cancel(Cancel),
    Unload(Unload),
    Stats(Stats),
    Error(ErrorMessage),
    Shutdown(Shutdown),
}

impl Message {
    /// The message id (unique per connection and direction).
    pub fn id(&self) -> u64 {
        match self {
            Self::Hello(m) => m.id,
            Self::Caps(m) => m.id,
            Self::Load(m) => m.id,
            Self::Loaded(m) => m.id,
            Self::Run(m) => m.id,
            Self::Progress(m) => m.id,
            Self::Result(m) => m.id,
            Self::Cancel(m) => m.id,
            Self::Unload(m) => m.id,
            Self::Stats(m) => m.id,
            Self::Error(m) => m.id,
            Self::Shutdown(m) => m.id,
        }
    }

    /// The JSON `type` value of this message.
    pub fn kind(&self) -> &'static str {
        match self {
            Self::Hello(_) => "hello",
            Self::Caps(_) => "caps",
            Self::Load(_) => "load",
            Self::Loaded(_) => "loaded",
            Self::Run(_) => "run",
            Self::Progress(_) => "progress",
            Self::Result(_) => "result",
            Self::Cancel(_) => "cancel",
            Self::Unload(_) => "unload",
            Self::Stats(_) => "stats",
            Self::Error(_) => "error",
            Self::Shutdown(_) => "shutdown",
        }
    }
}

/// Execution device: the CPU, or an index into the GPUs the host made
/// visible to the worker (0..=63). Serialized as `"cpu"` or an integer.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub enum Device {
    Cpu,
    Gpu(u8),
}

/// Highest GPU index the protocol accepts.
pub const MAX_GPU_INDEX: u8 = 63;

impl Serialize for Device {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        match self {
            Self::Cpu => serializer.serialize_str("cpu"),
            Self::Gpu(index) => serializer.serialize_u8(*index),
        }
    }
}

impl<'de> Deserialize<'de> for Device {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        struct DeviceVisitor;

        impl Visitor<'_> for DeviceVisitor {
            type Value = Device;

            fn expecting(&self, f: &mut fmt::Formatter) -> fmt::Result {
                write!(f, "\"cpu\" or a GPU index 0..={MAX_GPU_INDEX}")
            }

            fn visit_str<E: de::Error>(self, v: &str) -> Result<Device, E> {
                if v == "cpu" {
                    Ok(Device::Cpu)
                } else {
                    Err(E::invalid_value(de::Unexpected::Str(v), &self))
                }
            }

            fn visit_u64<E: de::Error>(self, v: u64) -> Result<Device, E> {
                match u8::try_from(v) {
                    Ok(index) if index <= MAX_GPU_INDEX => Ok(Device::Gpu(index)),
                    _ => Err(E::invalid_value(de::Unexpected::Unsigned(v), &self)),
                }
            }

            fn visit_i64<E: de::Error>(self, v: i64) -> Result<Device, E> {
                match u64::try_from(v) {
                    Ok(v) => self.visit_u64(v),
                    Err(_) => Err(E::invalid_value(de::Unexpected::Signed(v), &self)),
                }
            }
        }

        deserializer.deserialize_any(DeviceVisitor)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Precision {
    Fp32,
    Fp16,
    Bf16,
    Fp8,
    Int8,
    Int4,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Tier {
    Preview,
    Standard,
    Final,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum BufferKind {
    Frame,
    Mask,
    Audio,
    Tensor,
    Json,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum PixelFormat {
    Rgb8,
    Rgba8,
    Rgb16f,
    Rgba16f,
    Rgba32f,
    Gray8,
    Gray16,
    Gray32f,
    PcmF32,
    Utf8Json,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum ColorSpace {
    Srgb,
    Rec709,
    Rec2020Pq,
    Rec2020Hlg,
    LinearSrgb,
    Acescg,
}

/// A frame or tensor in a shared-memory segment the host created.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Buffer {
    /// POSIX shared-memory name, `/cfa4-ai-<name>`.
    pub shm: String,
    pub offset: u64,
    pub len: u64,
    pub kind: BufferKind,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub width: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub height: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub stride: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub frames: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub format: Option<PixelFormat>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub color: Option<ColorSpace>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub premultiplied: Option<bool>,
}

/// Frame indices in the source's own frame rate; the host converts to ticks.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FrameRange {
    pub start: u64,
    pub count: u32,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Chunk {
    pub index: u32,
    pub count: u32,
}

/// Protocol versions the host speaks, inclusive.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct VersionRange {
    pub min: u32,
    pub max: u32,
}

/// Host -> worker, first message on the socket.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Hello {
    pub id: u64,
    pub protocol: VersionRange,
    pub host: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct WorkerInfo {
    pub name: String,
    pub version: String,
    /// SPDX expression of the worker itself.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub license: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Limits {
    pub max_jobs: u32,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub max_buffer_bytes: Option<u64>,
    /// Usage cap a paid worker enforces itself, if any.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub max_duration_s: Option<f64>,
    /// Output-quality cap a paid worker enforces itself, if any.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub max_output_height: Option<u32>,
}

/// Worker -> host, answer to [`Hello`].
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Caps {
    pub id: u64,
    pub reply_to: u64,
    pub protocol: u32,
    pub worker: WorkerInfo,
    pub impls: Vec<String>,
    pub limits: Limits,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub devices: Option<Vec<Device>>,
}

/// Host -> worker: load an implementation's weights onto a device.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Load {
    pub id: u64,
    #[serde(rename = "impl")]
    pub implementation: String,
    pub device: Device,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub precision: Option<Precision>,
    /// Absolute path of the user's model folder.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub weights_dir: Option<String>,
}

/// Worker -> host: load finished.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Loaded {
    pub id: u64,
    pub reply_to: u64,
    #[serde(rename = "impl")]
    pub implementation: String,
    pub vram_mb: u64,
}

/// Host -> worker: run one job (or one chunk of a job).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Run {
    pub id: u64,
    pub job: String,
    #[serde(rename = "impl")]
    pub implementation: String,
    pub device: Device,
    pub inputs: Buffers,
    /// Buffers the host pre-allocated for the results.
    pub outputs: Buffers,
    pub params: Params,
    pub tier: Tier,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub seed: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub range: Option<FrameRange>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub chunk: Option<Chunk>,
}

/// Worker -> host, optional, any number per run.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Progress {
    pub id: u64,
    pub reply_to: u64,
    pub job: String,
    pub done: u64,
    pub total: u64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub stage: Option<String>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Metrics {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub elapsed_ms: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub peak_vram_mb: Option<u64>,
}

/// Worker -> host: the run finished and the output buffers are written.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RunResult {
    pub id: u64,
    pub reply_to: u64,
    pub job: String,
    pub outputs: Buffers,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub metrics: Option<Metrics>,
    /// True when the worker marked the output (e.g. synthetic-face policy).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub watermarked: Option<bool>,
}

/// Host -> worker. The worker answers the run with [`ErrorCode::Cancelled`].
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Cancel {
    pub id: u64,
    pub job: String,
}

/// Host -> worker: free an implementation on one device, or on every device
/// when `device` is absent. Answered by [`Stats`].
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Unload {
    pub id: u64,
    #[serde(rename = "impl")]
    pub implementation: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub device: Option<Device>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Residency {
    #[serde(rename = "impl")]
    pub implementation: String,
    pub device: Device,
    pub vram_mb: u64,
}

/// Worker -> host: current residency, after unload or unprompted.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Stats {
    pub id: u64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub reply_to: Option<u64>,
    pub loaded: Vec<Residency>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub rss_mb: Option<u64>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ErrorCode {
    Oom,
    InvalidInput,
    ModelError,
    ModelMissing,
    Unsupported,
    LimitReached,
    Cancelled,
    Protocol,
    Crash,
}

/// Either direction. Answers a request when `reply_to` is set.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ErrorMessage {
    pub id: u64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub reply_to: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub job: Option<String>,
    pub code: ErrorCode,
    pub message: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub retryable: Option<bool>,
}

/// Host -> worker: finish or cancel jobs, unload and exit 0.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Shutdown {
    pub id: u64,
}
