pub mod decoder;
pub mod replica;
pub mod wire;

pub use decoder::{DecodeError, FrameDecoder};
pub use replica::{ApplyError, ApplyOutcome, Replica};
pub use wire::{Frame, Operation, encode_frame};
