use std::collections::{BTreeMap, HashMap};

use crate::decoder::{DecodeError, FrameDecoder};
use crate::wire::{Frame, Operation};

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ApplyError {
    SequenceGap { expected: u64, received: u64 },
    TransactionAlreadyOpen(u64),
    TransactionNotOpen(u64),
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ApplyOutcome {
    Applied(u64),
    Duplicate(u64),
    Rejected { sequence: u64, error: ApplyError },
    DecodeRejected(DecodeError),
}

#[derive(Default)]
struct Transaction {
    operations: Vec<Operation>,
}

pub struct Replica {
    decoder: FrameDecoder,
    values: BTreeMap<String, Vec<u8>>,
    transactions: HashMap<u64, Transaction>,
    last_sequence: u64,
}

impl Replica {
    pub fn new(max_payload: usize) -> Self {
        Self {
            decoder: FrameDecoder::new(max_payload),
            values: BTreeMap::new(),
            transactions: HashMap::new(),
            last_sequence: 0,
        }
    }

    pub fn ingest(&mut self, bytes: &[u8]) -> Vec<ApplyOutcome> {
        let _ = bytes;
        Vec::new()
    }

    fn apply(&mut self, _frame: Frame) -> ApplyOutcome {
        ApplyOutcome::Rejected {
            sequence: 0,
            error: ApplyError::SequenceGap {
                expected: self.last_sequence + 1,
                received: 0,
            },
        }
    }

    pub fn get(&self, key: &str) -> Option<&[u8]> {
        self.values.get(key).map(Vec::as_slice)
    }

    pub fn last_sequence(&self) -> u64 {
        self.last_sequence
    }

    pub fn open_transactions(&self) -> usize {
        self.transactions.len()
    }

    pub fn buffered_bytes(&self) -> usize {
        self.decoder.buffered_len()
    }
}
