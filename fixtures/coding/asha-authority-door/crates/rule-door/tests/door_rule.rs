use core_state::{
    DoorCapability, DoorPosition as StatePosition, EnergyCapability, EntityId, RuntimeSession,
};
use protocol_door::{DoorIntent, DoorPosition};
use rule_door::{DoorRuleError, TRANSITION_COOLDOWN_TICKS, transition};

fn session(energy: u32) -> RuntimeSession {
    let mut session = RuntimeSession::default();
    assert!(session.insert_entity(
        EntityId(7),
        DoorCapability {
            position: StatePosition::Closed,
            open_energy_cost: 4,
            cooldown_until_tick: 0,
            revision: 2,
        },
        EnergyCapability { available: energy },
    ));
    session
}

fn open_intent() -> DoorIntent {
    DoorIntent {
        entity_id: 7,
        desired: DoorPosition::Open,
        expected_revision: 2,
        observed_tick: 10,
    }
}

#[test]
fn accepted_transition_emits_then_applies_authority_event() {
    let mut session = session(9);
    let event = transition(&mut session, &open_intent()).expect("open accepted");

    assert_eq!(event.energy_spent, 4);
    assert_eq!(event.revision, 3);
    assert_eq!(event.cooldown_until_tick, 10 + TRANSITION_COOLDOWN_TICKS);
    assert_eq!(
        session.door(EntityId(7)).unwrap().position,
        StatePosition::Open
    );
    assert_eq!(session.door(EntityId(7)).unwrap().revision, 3);
    assert_eq!(session.energy(EntityId(7)).unwrap().available, 5);
}

#[test]
fn rejected_transition_is_atomic() {
    let mut session = session(3);
    let before = session.clone();
    assert_eq!(
        transition(&mut session, &open_intent()),
        Err(DoorRuleError::InsufficientEnergy {
            required: 4,
            available: 3
        })
    );
    assert_eq!(session, before);
}

#[test]
fn stale_revision_is_rejected_before_mutation() {
    let mut session = session(9);
    let before = session.clone();
    let mut intent = open_intent();
    intent.expected_revision = 1;
    assert!(matches!(
        transition(&mut session, &intent),
        Err(DoorRuleError::StaleRevision { .. })
    ));
    assert_eq!(session, before);
}
