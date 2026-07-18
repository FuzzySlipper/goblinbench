use core_state::RuntimeSession;
use protocol_door::{DoorDomainEvent, DoorIntent};

pub const TRANSITION_COOLDOWN_TICKS: u64 = 5;

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum DoorRuleError {
    UnknownEntity(u64),
    MissingDoor(u64),
    MissingEnergy(u64),
    StaleRevision { expected: u64, received: u64 },
    CoolingDown { ready_at: u64, observed: u64 },
    AlreadyInDesiredState,
    InsufficientEnergy { required: u32, available: u32 },
    ArithmeticOverflow,
    ApplyRejected(DoorApplyError),
    NotImplemented,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum DoorApplyError {
    MissingDoor(u64),
    MissingEnergy(u64),
    PreviousStateMismatch,
    InvalidTransition,
    InvalidEnergySpend,
    InvalidRevision { expected: u64, received: u64 },
    InvalidCooldown,
    ArithmeticOverflow,
    NotImplemented,
}

pub fn evaluate(
    _session: &RuntimeSession,
    _intent: &DoorIntent,
) -> Result<DoorDomainEvent, DoorRuleError> {
    Err(DoorRuleError::NotImplemented)
}

pub fn apply(
    _session: &mut RuntimeSession,
    _event: &DoorDomainEvent,
) -> Result<(), DoorApplyError> {
    Err(DoorApplyError::NotImplemented)
}

pub fn transition(
    session: &mut RuntimeSession,
    intent: &DoorIntent,
) -> Result<DoorDomainEvent, DoorRuleError> {
    let event = evaluate(session, intent)?;
    apply(session, &event).map_err(DoorRuleError::ApplyRejected)?;
    Ok(event)
}
