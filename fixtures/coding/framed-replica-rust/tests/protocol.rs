use framed_replica::{
    ApplyError, ApplyOutcome, DecodeError, FrameDecoder, Operation, Replica, encode_frame,
};

fn begin(sequence: u64, tx: u64) -> Vec<u8> {
    encode_frame(sequence, &Operation::Begin { tx })
}

fn put(sequence: u64, tx: u64, key: &str, value: &[u8]) -> Vec<u8> {
    encode_frame(
        sequence,
        &Operation::Put {
            tx,
            key: key.into(),
            value: value.to_vec(),
        },
    )
}

fn delete(sequence: u64, tx: u64, key: &str) -> Vec<u8> {
    encode_frame(
        sequence,
        &Operation::Delete {
            tx,
            key: key.into(),
        },
    )
}

fn commit(sequence: u64, tx: u64) -> Vec<u8> {
    encode_frame(sequence, &Operation::Commit { tx })
}

fn abort(sequence: u64, tx: u64) -> Vec<u8> {
    encode_frame(sequence, &Operation::Abort { tx })
}

fn concat(frames: &[Vec<u8>]) -> Vec<u8> {
    frames
        .iter()
        .flat_map(|frame| frame.iter().copied())
        .collect()
}

#[test]
fn decoder_retains_every_partial_prefix_until_frame_is_complete() {
    let bytes = put(7, 4, "key|with|pipes", b"binary\0value");
    let mut decoder = FrameDecoder::new(1024);
    let mut outcomes = Vec::new();
    for byte in bytes {
        outcomes.extend(decoder.push(&[byte]));
    }

    assert_eq!(outcomes.len(), 1);
    let frame = outcomes.pop().unwrap().unwrap();
    assert_eq!(frame.sequence, 7);
    assert_eq!(
        frame.operation,
        Operation::Put {
            tx: 4,
            key: "key|with|pipes".into(),
            value: b"binary\0value".to_vec()
        }
    );
    assert_eq!(decoder.buffered_len(), 0);
}

#[test]
fn decoder_emits_multiple_frames_from_one_chunk() {
    let bytes = concat(&[begin(1, 9), put(2, 9, "a", b"one"), commit(3, 9)]);
    let mut decoder = FrameDecoder::new(1024);
    let frames = decoder.push(&bytes);

    assert_eq!(frames.len(), 3);
    assert_eq!(
        frames
            .into_iter()
            .map(|frame| frame.unwrap().sequence)
            .collect::<Vec<_>>(),
        [1, 2, 3]
    );
}

#[test]
fn decoder_discards_noise_and_resynchronizes_on_magic_prefix() {
    let mut bytes = b"noise-G".to_vec();
    bytes.extend_from_slice(&begin(1, 3));
    let mut decoder = FrameDecoder::new(1024);
    let frames = decoder.push(&bytes);

    assert_eq!(frames.len(), 1);
    assert_eq!(frames[0].as_ref().unwrap().sequence, 1);
    assert_eq!(decoder.discarded_bytes(), 7);
}

#[test]
fn checksum_failure_does_not_consume_the_following_valid_frame() {
    let mut corrupt = begin(1, 3);
    let payload_index = 15;
    corrupt[payload_index] ^= 0x55;
    let bytes = concat(&[corrupt, begin(1, 4)]);
    let mut decoder = FrameDecoder::new(1024);
    let outcomes = decoder.push(&bytes);

    assert_eq!(outcomes.len(), 2);
    assert_eq!(outcomes[0], Err(DecodeError::ChecksumMismatch));
    assert_eq!(
        outcomes[1].as_ref().unwrap().operation,
        Operation::Begin { tx: 4 }
    );
}

#[test]
fn oversized_header_is_rejected_without_allocating_or_losing_next_frame() {
    let mut oversized = vec![b'G', b'B', 1];
    oversized.extend_from_slice(&1_u64.to_be_bytes());
    oversized.extend_from_slice(&65_536_u32.to_be_bytes());
    oversized.extend_from_slice(&begin(1, 8));
    let mut decoder = FrameDecoder::new(32);
    let outcomes = decoder.push(&oversized);

    assert_eq!(outcomes.len(), 2);
    assert_eq!(outcomes[0], Err(DecodeError::OversizedPayload(65_536)));
    assert_eq!(
        outcomes[1].as_ref().unwrap().operation,
        Operation::Begin { tx: 8 }
    );
    assert!(decoder.buffered_len() <= 1);
}

#[test]
fn transaction_writes_remain_invisible_until_commit_then_apply_atomically() {
    let mut replica = Replica::new(1024);
    assert_eq!(
        replica.ingest(&concat(&[
            begin(1, 1),
            put(2, 1, "alpha", b"A"),
            put(3, 1, "beta", b"B")
        ])),
        [
            ApplyOutcome::Applied(1),
            ApplyOutcome::Applied(2),
            ApplyOutcome::Applied(3)
        ]
    );
    assert_eq!(replica.get("alpha"), None);
    assert_eq!(replica.open_transactions(), 1);

    assert_eq!(replica.ingest(&commit(4, 1)), [ApplyOutcome::Applied(4)]);
    assert_eq!(replica.get("alpha"), Some(&b"A"[..]));
    assert_eq!(replica.get("beta"), Some(&b"B"[..]));
    assert_eq!(replica.open_transactions(), 0);
}

#[test]
fn abort_discards_staged_mutations_and_delete_is_transactional() {
    let mut replica = Replica::new(1024);
    replica.ingest(&concat(&[
        begin(1, 1),
        put(2, 1, "key", b"original"),
        commit(3, 1),
    ]));
    replica.ingest(&concat(&[begin(4, 2), delete(5, 2, "key"), abort(6, 2)]));
    assert_eq!(replica.get("key"), Some(&b"original"[..]));

    replica.ingest(&concat(&[begin(7, 3), delete(8, 3, "key"), commit(9, 3)]));
    assert_eq!(replica.get("key"), None);
}

#[test]
fn duplicate_sequence_is_idempotent_and_never_applies_twice() {
    let mut replica = Replica::new(1024);
    let frame = begin(1, 7);
    assert_eq!(replica.ingest(&frame), [ApplyOutcome::Applied(1)]);
    assert_eq!(replica.ingest(&frame), [ApplyOutcome::Duplicate(1)]);
    assert_eq!(replica.last_sequence(), 1);
    assert_eq!(replica.open_transactions(), 1);
}

#[test]
fn sequence_gap_is_rejected_without_advancing_and_missing_frame_can_follow() {
    let mut replica = Replica::new(1024);
    assert_eq!(
        replica.ingest(&begin(2, 2)),
        [ApplyOutcome::Rejected {
            sequence: 2,
            error: ApplyError::SequenceGap {
                expected: 1,
                received: 2
            },
        }]
    );
    assert_eq!(replica.last_sequence(), 0);
    assert_eq!(replica.ingest(&begin(1, 1)), [ApplyOutcome::Applied(1)]);
    assert_eq!(replica.ingest(&begin(2, 2)), [ApplyOutcome::Applied(2)]);
}

#[test]
fn invalid_transaction_transition_does_not_advance_sequence() {
    let mut replica = Replica::new(1024);
    assert_eq!(
        replica.ingest(&commit(1, 99)),
        [ApplyOutcome::Rejected {
            sequence: 1,
            error: ApplyError::TransactionNotOpen(99),
        }]
    );
    assert_eq!(replica.last_sequence(), 0);
    assert_eq!(replica.ingest(&begin(1, 99)), [ApplyOutcome::Applied(1)]);
}

#[test]
fn duplicate_begin_is_rejected_without_destroying_original_transaction() {
    let mut replica = Replica::new(1024);
    replica.ingest(&begin(1, 11));
    assert_eq!(
        replica.ingest(&begin(2, 11)),
        [ApplyOutcome::Rejected {
            sequence: 2,
            error: ApplyError::TransactionAlreadyOpen(11),
        }]
    );
    assert_eq!(replica.open_transactions(), 1);
    assert_eq!(replica.last_sequence(), 1);
    assert_eq!(
        replica.ingest(&put(2, 11, "key", b"value")),
        [ApplyOutcome::Applied(2)]
    );
}

#[test]
fn decode_error_does_not_advance_replication_sequence() {
    let mut replica = Replica::new(1024);
    let mut corrupt = begin(1, 1);
    let last = corrupt.len() - 1;
    corrupt[last] ^= 1;
    assert_eq!(
        replica.ingest(&corrupt),
        [ApplyOutcome::DecodeRejected(DecodeError::ChecksumMismatch)]
    );
    assert_eq!(replica.last_sequence(), 0);
    assert_eq!(replica.ingest(&begin(1, 1)), [ApplyOutcome::Applied(1)]);
}
