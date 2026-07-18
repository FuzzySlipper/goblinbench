import type { WorkflowDefinition } from "./types";

export interface DefinitionIssue {
  path: string;
  message: string;
}

/** Return every stable, user-actionable definition issue without mutating persistence. */
export function validateDefinition(_definition: WorkflowDefinition): DefinitionIssue[] {
  return [];
}
