use core_state::RuntimeSession;
use protocol_door::DoorDomainEvent;
use rule_door::{DoorApplyError, apply};

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ReplayError {
    pub event_index: usize,
    pub source: DoorApplyError,
}

pub fn replay(
    initial: &RuntimeSession,
    events: &[DoorDomainEvent],
) -> Result<RuntimeSession, ReplayError> {
    let mut session = initial.clone();
    for (event_index, event) in events.iter().enumerate() {
        apply(&mut session, event).map_err(|source| ReplayError {
            event_index,
            source,
        })?;
    }
    Ok(session)
}

/// Stable FNV-1a hash over explicitly ordered authority fields.
pub fn stable_state_hash(session: &RuntimeSession) -> u64 {
    let mut hash = 0xcbf29ce484222325_u64;
    for entity_id in session.entity_ids() {
        let door = session
            .door(entity_id)
            .expect("door id came from door table");
        let energy = session
            .energy(entity_id)
            .expect("authority tables stay aligned");
        let position = match door.position {
            core_state::DoorPosition::Closed => 0_u8,
            core_state::DoorPosition::Open => 1_u8,
        };
        for byte in entity_id
            .0
            .to_le_bytes()
            .into_iter()
            .chain([position])
            .chain(door.open_energy_cost.to_le_bytes())
            .chain(door.cooldown_until_tick.to_le_bytes())
            .chain(door.revision.to_le_bytes())
            .chain(energy.available.to_le_bytes())
        {
            hash ^= u64::from(byte);
            hash = hash.wrapping_mul(0x100000001b3);
        }
    }
    hash
}
