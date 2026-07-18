use std::collections::BTreeMap;

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub struct EntityId(pub u64);

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum DoorPosition {
    Closed,
    Open,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DoorCapability {
    pub position: DoorPosition,
    pub open_energy_cost: u32,
    pub cooldown_until_tick: u64,
    pub revision: u64,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct EnergyCapability {
    pub available: u32,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct RuntimeSession {
    doors: BTreeMap<EntityId, DoorCapability>,
    energy: BTreeMap<EntityId, EnergyCapability>,
}

impl RuntimeSession {
    pub fn insert_entity(
        &mut self,
        entity_id: EntityId,
        door: DoorCapability,
        energy: EnergyCapability,
    ) -> bool {
        if self.doors.contains_key(&entity_id) || self.energy.contains_key(&entity_id) {
            return false;
        }
        self.doors.insert(entity_id, door);
        self.energy.insert(entity_id, energy);
        true
    }

    pub fn door(&self, entity_id: EntityId) -> Option<&DoorCapability> {
        self.doors.get(&entity_id)
    }

    pub fn energy(&self, entity_id: EntityId) -> Option<&EnergyCapability> {
        self.energy.get(&entity_id)
    }

    /// Narrow mutation surface consumed by the registered door Rule owner.
    pub fn door_for_transition(&mut self, entity_id: EntityId) -> Option<&mut DoorCapability> {
        self.doors.get_mut(&entity_id)
    }

    /// Narrow mutation surface consumed by the registered door Rule owner.
    pub fn energy_for_transition(&mut self, entity_id: EntityId) -> Option<&mut EnergyCapability> {
        self.energy.get_mut(&entity_id)
    }

    pub fn entity_ids(&self) -> impl Iterator<Item = EntityId> + '_ {
        self.doors.keys().copied()
    }
}
