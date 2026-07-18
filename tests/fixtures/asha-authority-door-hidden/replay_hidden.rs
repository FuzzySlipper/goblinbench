use core_state::{
    DoorCapability, DoorPosition as StatePosition, EnergyCapability, EntityId, RuntimeSession,
};
use protocol_door::{DoorIntent, DoorPosition};
use rule_door::transition;
use sim_replay::{replay, stable_state_hash};

fn state(order: &[u64]) -> RuntimeSession {
    let mut session = RuntimeSession::default();
    for id in order {
        assert!(session.insert_entity(
            EntityId(*id),
            DoorCapability {
                position: StatePosition::Closed,
                open_energy_cost: *id as u32,
                cooldown_until_tick: 0,
                revision: 0,
            },
            EnergyCapability { available: 20 },
        ));
    }
    session
}

#[test]
fn stable_hash_ignores_insertion_order() {
    assert_eq!(
        stable_state_hash(&state(&[2, 1])),
        stable_state_hash(&state(&[1, 2]))
    );
}

#[test]
fn duplicate_or_out_of_order_replay_event_is_reported_at_its_index() {
    let initial = state(&[2]);
    let mut live = initial.clone();
    let event = transition(
        &mut live,
        &DoorIntent {
            entity_id: 2,
            desired: DoorPosition::Open,
            expected_revision: 0,
            observed_tick: 10,
        },
    )
    .expect("event");
    let error = replay(&initial, &[event.clone(), event]).expect_err("duplicate must fail");
    assert_eq!(error.event_index, 1);
}
