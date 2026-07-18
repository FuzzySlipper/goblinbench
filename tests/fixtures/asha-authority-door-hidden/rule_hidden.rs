use core_state::{
    DoorCapability, DoorPosition as StatePosition, EnergyCapability, EntityId, RuntimeSession,
};
use protocol_door::{DoorDomainEvent, DoorIntent, DoorPosition};
use rule_door::{DoorApplyError, DoorRuleError, apply, evaluate, transition};

fn closed_session() -> RuntimeSession {
    let mut session = RuntimeSession::default();
    assert!(session.insert_entity(
        EntityId(19),
        DoorCapability {
            position: StatePosition::Closed,
            open_energy_cost: 6,
            cooldown_until_tick: 0,
            revision: 8,
        },
        EnergyCapability { available: 10 },
    ));
    session
}

fn intent(desired: DoorPosition, tick: u64, revision: u64) -> DoorIntent {
    DoorIntent {
        entity_id: 19,
        desired,
        expected_revision: revision,
        observed_tick: tick,
    }
}

#[test]
fn evaluation_is_pure_and_cooldown_is_authoritative() {
    let session = closed_session();
    let before = session.clone();
    let event = evaluate(&session, &intent(DoorPosition::Open, 40, 8)).expect("evaluation");
    assert_eq!(session, before);
    assert_eq!(event.energy_spent, 6);

    let mut live = session;
    transition(&mut live, &intent(DoorPosition::Open, 40, 8)).expect("open");
    let after_open = live.clone();
    assert!(matches!(
        transition(&mut live, &intent(DoorPosition::Closed, 44, 9)),
        Err(DoorRuleError::CoolingDown {
            ready_at: 45,
            observed: 44
        })
    ));
    assert_eq!(live, after_open);

    let closed = transition(&mut live, &intent(DoorPosition::Closed, 45, 9)).expect("close");
    assert_eq!(closed.energy_spent, 0);
    assert_eq!(live.energy(EntityId(19)).unwrap().available, 4);
}

#[test]
fn corrupt_event_is_rejected_without_partial_mutation() {
    let mut session = closed_session();
    let before = session.clone();
    let corrupt = DoorDomainEvent {
        entity_id: 19,
        previous: DoorPosition::Closed,
        current: DoorPosition::Open,
        energy_spent: 1,
        accepted_tick: 40,
        cooldown_until_tick: 45,
        revision: 9,
    };
    assert_eq!(
        apply(&mut session, &corrupt),
        Err(DoorApplyError::InvalidEnergySpend)
    );
    assert_eq!(session, before);
}

#[test]
fn tick_overflow_and_unknown_entity_fail_closed() {
    let session = closed_session();
    assert_eq!(
        evaluate(&session, &intent(DoorPosition::Open, u64::MAX, 8)),
        Err(DoorRuleError::ArithmeticOverflow)
    );
    let missing = DoorIntent {
        entity_id: 999,
        desired: DoorPosition::Open,
        expected_revision: 0,
        observed_tick: 1,
    };
    assert_eq!(
        evaluate(&session, &missing),
        Err(DoorRuleError::UnknownEntity(999))
    );
}
