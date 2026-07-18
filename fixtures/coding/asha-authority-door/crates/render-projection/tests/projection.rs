use core_state::{DoorCapability, DoorPosition, EnergyCapability, EntityId, RuntimeSession};
use protocol_door::DoorPosition as WirePosition;
use render_projection::project_door;

#[test]
fn projection_is_derived_from_authority() {
    let mut session = RuntimeSession::default();
    assert!(session.insert_entity(
        EntityId(11),
        DoorCapability {
            position: DoorPosition::Open,
            open_energy_cost: 1,
            cooldown_until_tick: 9,
            revision: 4,
        },
        EnergyCapability { available: 8 },
    ));
    let projection = project_door(&session, EntityId(11)).expect("projection");
    assert_eq!(projection.position, WirePosition::Open);
    assert_eq!(projection.openness_milli, 1000);
    assert_eq!(projection.revision, 4);
}
