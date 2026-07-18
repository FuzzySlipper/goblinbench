use core_state::{DoorPosition as StatePosition, EntityId, RuntimeSession};
use protocol_door::{DoorPosition, DoorProjection};

pub fn project_door(session: &RuntimeSession, entity_id: EntityId) -> Option<DoorProjection> {
    let door = session.door(entity_id)?;
    let (position, openness_milli) = match door.position {
        StatePosition::Closed => (DoorPosition::Closed, 0),
        StatePosition::Open => (DoorPosition::Open, 1000),
    };
    Some(DoorProjection {
        entity_id: entity_id.0,
        position,
        openness_milli,
        revision: door.revision,
    })
}
