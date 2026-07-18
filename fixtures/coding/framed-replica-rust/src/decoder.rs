use crate::wire::Frame;

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum DecodeError {
    InvalidVersion(u8),
    OversizedPayload(usize),
    ChecksumMismatch,
    MalformedPayload,
}

pub struct FrameDecoder {
    buffer: Vec<u8>,
    max_payload: usize,
    discarded_bytes: usize,
}

impl FrameDecoder {
    pub fn new(max_payload: usize) -> Self {
        Self {
            buffer: Vec::new(),
            max_payload,
            discarded_bytes: 0,
        }
    }

    /// Incrementally decode zero or more frames while retaining an incomplete tail.
    /// Invalid data must resynchronize at the next magic prefix.
    pub fn push(&mut self, bytes: &[u8]) -> Vec<Result<Frame, DecodeError>> {
        self.buffer.extend_from_slice(bytes);
        Vec::new()
    }

    pub fn buffered_len(&self) -> usize {
        self.buffer.len()
    }

    pub fn discarded_bytes(&self) -> usize {
        self.discarded_bytes
    }

    pub fn max_payload(&self) -> usize {
        self.max_payload
    }
}
