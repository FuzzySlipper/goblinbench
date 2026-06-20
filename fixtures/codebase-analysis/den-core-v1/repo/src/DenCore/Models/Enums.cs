namespace DenCore.Models;

/// <summary>Core status values for task lifecycle.</summary>
public enum TaskStatus
{
    Planned = 0,
    InProgress = 1,
    Review = 2,
    Blocked = 3,
    Done = 4,
    Cancelled = 5
}

/// <summary>Priority levels. Lower number = higher urgency.</summary>
public enum Priority
{
    Critical = 1,
    High = 2,
    Medium = 3,
    Low = 4,
    Backlog = 5
}

/// <summary>Delivery routing for outbound messages.</summary>
public enum DeliveryKind
{
    Direct = 0,
    Gateway = 1,
    Broadcast = 2,
    MCPTool = 3
}

/// <summary>Worker pool membership state.</summary>
public enum PoolMemberStatus
{
    Available = 0,
    Busy = 1,
    Quarantined = 2,
    Offboarded = 3
}

/// <summary>Review verdict for change requests.</summary>
public enum ReviewVerdict
{
    Pending = 0,
    Approved = 1,
    ChangesRequested = 2,
    Rejected = 3
}

/// <summary>Document category taxonomy.</summary>
public enum DocumentKind
{
    Spec = 0,
    Adr = 1,
    Convention = 2,
    Reference = 3,
    Note = 4,
    Memory = 5
}

/// <summary>Background dispatch processing phase.</summary>
public enum DispatchPhase
{
    Queued = 0,
    Processing = 1,
    Completed = 2,
    Failed = 3
}
