use core_state::{DoorPosition as StatePosition, EntityId, RuntimeSession};
use protocol_door::{DoorDomainEvent, DoorIntent, DoorPosition};

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
    session: &RuntimeSession,
    intent: &DoorIntent,
) -> Result<DoorDomainEvent, DoorRuleError> {
    let entity_id = EntityId(intent.entity_id);
    let door = match session.door(entity_id) {
        Some(door) => door,
        None if session.energy(entity_id).is_none() => {
            return Err(DoorRuleError::UnknownEntity(intent.entity_id));
        }
        None => return Err(DoorRuleError::MissingDoor(intent.entity_id)),
    };
    let energy = session
        .energy(entity_id)
        .ok_or(DoorRuleError::MissingEnergy(intent.entity_id))?;

    if intent.expected_revision != door.revision {
        return Err(DoorRuleError::StaleRevision {
            expected: door.revision,
            received: intent.expected_revision,
        });
    }
    if intent.observed_tick < door.cooldown_until_tick {
        return Err(DoorRuleError::CoolingDown {
            ready_at: door.cooldown_until_tick,
            observed: intent.observed_tick,
        });
    }

    let previous = wire_position(door.position);
    if intent.desired == previous {
        return Err(DoorRuleError::AlreadyInDesiredState);
    }
    let energy_spent = match (previous, intent.desired) {
        (DoorPosition::Closed, DoorPosition::Open) => door.open_energy_cost,
        (DoorPosition::Open, DoorPosition::Closed) => 0,
        _ => return Err(DoorRuleError::AlreadyInDesiredState),
    };
    if energy.available < energy_spent {
        return Err(DoorRuleError::InsufficientEnergy {
            required: energy_spent,
            available: energy.available,
        });
    }
    let cooldown_until_tick = intent
        .observed_tick
        .checked_add(TRANSITION_COOLDOWN_TICKS)
        .ok_or(DoorRuleError::ArithmeticOverflow)?;
    let revision = door
        .revision
        .checked_add(1)
        .ok_or(DoorRuleError::ArithmeticOverflow)?;

    Ok(DoorDomainEvent {
        entity_id: intent.entity_id,
        previous,
        current: intent.desired,
        energy_spent,
        accepted_tick: intent.observed_tick,
        cooldown_until_tick,
        revision,
    })
}

pub fn apply(session: &mut RuntimeSession, event: &DoorDomainEvent) -> Result<(), DoorApplyError> {
    let entity_id = EntityId(event.entity_id);
    let door = session
        .door(entity_id)
        .ok_or(DoorApplyError::MissingDoor(event.entity_id))?;
    let energy = session
        .energy(entity_id)
        .ok_or(DoorApplyError::MissingEnergy(event.entity_id))?;

    if wire_position(door.position) != event.previous {
        return Err(DoorApplyError::PreviousStateMismatch);
    }
    let expected_spend = match (event.previous, event.current) {
        (DoorPosition::Closed, DoorPosition::Open) => door.open_energy_cost,
        (DoorPosition::Open, DoorPosition::Closed) => 0,
        _ => return Err(DoorApplyError::InvalidTransition),
    };
    if event.energy_spent != expected_spend || energy.available < event.energy_spent {
        return Err(DoorApplyError::InvalidEnergySpend);
    }
    let expected_revision = door
        .revision
        .checked_add(1)
        .ok_or(DoorApplyError::ArithmeticOverflow)?;
    if event.revision != expected_revision {
        return Err(DoorApplyError::InvalidRevision {
            expected: expected_revision,
            received: event.revision,
        });
    }
    let expected_cooldown = event
        .accepted_tick
        .checked_add(TRANSITION_COOLDOWN_TICKS)
        .ok_or(DoorApplyError::ArithmeticOverflow)?;
    if event.cooldown_until_tick != expected_cooldown {
        return Err(DoorApplyError::InvalidCooldown);
    }

    let remaining_energy = energy.available - event.energy_spent;
    let door = session
        .door_for_transition(entity_id)
        .ok_or(DoorApplyError::MissingDoor(event.entity_id))?;
    door.position = state_position(event.current);
    door.cooldown_until_tick = event.cooldown_until_tick;
    door.revision = event.revision;
    session
        .energy_for_transition(entity_id)
        .ok_or(DoorApplyError::MissingEnergy(event.entity_id))?
        .available = remaining_energy;
    Ok(())
}

pub fn transition(
    session: &mut RuntimeSession,
    intent: &DoorIntent,
) -> Result<DoorDomainEvent, DoorRuleError> {
    let event = evaluate(session, intent)?;
    apply(session, &event).map_err(DoorRuleError::ApplyRejected)?;
    Ok(event)
}

fn wire_position(position: StatePosition) -> DoorPosition {
    match position {
        StatePosition::Closed => DoorPosition::Closed,
        StatePosition::Open => DoorPosition::Open,
    }
}

fn state_position(position: DoorPosition) -> StatePosition {
    match position {
        DoorPosition::Closed => StatePosition::Closed,
        DoorPosition::Open => StatePosition::Open,
    }
}
