use core_state::{
    DoorCapability, DoorPosition as StatePosition, EnergyCapability, EntityId, RuntimeSession,
};
use protocol_door::{DoorIntent, DoorPosition};
use rule_door::transition;
use sim_replay::{replay, stable_state_hash};

fn initial() -> RuntimeSession {
    let mut state = RuntimeSession::default();
    assert!(state.insert_entity(
        EntityId(3),
        DoorCapability {
            position: StatePosition::Closed,
            open_energy_cost: 2,
            cooldown_until_tick: 0,
            revision: 0,
        },
        EnergyCapability { available: 6 },
    ));
    state
}

#[test]
fn replay_reproduces_live_authority_hash() {
    let initial = initial();
    let mut live = initial.clone();
    let event = transition(
        &mut live,
        &DoorIntent {
            entity_id: 3,
            desired: DoorPosition::Open,
            expected_revision: 0,
            observed_tick: 20,
        },
    )
    .expect("live transition");

    let replayed = replay(&initial, &[event]).expect("replay");
    assert_eq!(replayed, live);
    assert_eq!(stable_state_hash(&replayed), stable_state_hash(&live));
}
