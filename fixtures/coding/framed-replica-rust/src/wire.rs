pub const MAGIC: &[u8; 2] = b"GB";
pub const VERSION: u8 = 1;
pub const HEADER_LEN: usize = 15;
pub const TRAILER_LEN: usize = 4;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Frame {
    pub sequence: u64,
    pub operation: Operation,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Operation {
    Begin {
        tx: u64,
    },
    Put {
        tx: u64,
        key: String,
        value: Vec<u8>,
    },
    Delete {
        tx: u64,
        key: String,
    },
    Commit {
        tx: u64,
    },
    Abort {
        tx: u64,
    },
}

pub fn encode_frame(sequence: u64, operation: &Operation) -> Vec<u8> {
    let payload = encode_operation(operation);
    let mut bytes = Vec::with_capacity(HEADER_LEN + payload.len() + TRAILER_LEN);
    bytes.extend_from_slice(MAGIC);
    bytes.push(VERSION);
    bytes.extend_from_slice(&sequence.to_be_bytes());
    bytes.extend_from_slice(&(payload.len() as u32).to_be_bytes());
    bytes.extend_from_slice(&payload);
    let checksum = checksum(&bytes[2..]);
    bytes.extend_from_slice(&checksum.to_be_bytes());
    bytes
}

pub fn checksum(bytes: &[u8]) -> u32 {
    bytes.iter().fold(2_166_136_261_u32, |hash, byte| {
        (hash ^ u32::from(*byte)).wrapping_mul(16_777_619)
    })
}

pub fn encode_operation(operation: &Operation) -> Vec<u8> {
    let mut bytes = Vec::new();
    match operation {
        Operation::Begin { tx } => push_tx(&mut bytes, 1, *tx),
        Operation::Put { tx, key, value } => {
            push_tx(&mut bytes, 2, *tx);
            push_string(&mut bytes, key);
            bytes.extend_from_slice(&(value.len() as u32).to_be_bytes());
            bytes.extend_from_slice(value);
        }
        Operation::Delete { tx, key } => {
            push_tx(&mut bytes, 3, *tx);
            push_string(&mut bytes, key);
        }
        Operation::Commit { tx } => push_tx(&mut bytes, 4, *tx),
        Operation::Abort { tx } => push_tx(&mut bytes, 5, *tx),
    }
    bytes
}

fn push_tx(bytes: &mut Vec<u8>, opcode: u8, tx: u64) {
    bytes.push(opcode);
    bytes.extend_from_slice(&tx.to_be_bytes());
}

fn push_string(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(&(value.len() as u16).to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}
