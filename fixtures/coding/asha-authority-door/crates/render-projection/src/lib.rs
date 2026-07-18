use core_state::{EntityId, RuntimeSession};
use protocol_door::DoorProjection;

pub fn project_door(_session: &RuntimeSession, _entity_id: EntityId) -> Option<DoorProjection> {
    None
}
