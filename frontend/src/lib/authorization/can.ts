export type AuthorizationDecisionSet = {
	allowed: readonly string[];
	relations?: Readonly<Record<string, readonly string[]>>;
};

/** Ask a server-authored decision set; never infer policy from roles or lifecycle in the UI. */
export function can(
	decisions: AuthorizationDecisionSet | null | undefined,
	resource: string,
	action: string,
	relation?: string
): boolean {
	const key = `${resource}.${action}`;
	if (!decisions?.allowed.includes(key)) return false;
	if (relation === undefined) return true;
	const constrainedRelations = decisions.relations?.[key];
	return constrainedRelations === undefined || constrainedRelations.includes(relation);
}

/** Whether the server projected at least one concrete action for this surface. */
export function hasAllowedAction(decisions: AuthorizationDecisionSet | null | undefined): boolean {
	return Boolean(decisions?.allowed.length);
}
