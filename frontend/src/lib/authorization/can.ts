import type { components } from '$lib/api/schema';

export type AuthorizationAction = components['schemas']['AuthorizationView']['allowed'][number];
export type AuthorizationDecisionSet = Pick<
	components['schemas']['AuthorizationView'],
	'allowed' | 'relations'
>;

/** Ask a server-authored decision set; never infer policy from roles or lifecycle in the UI. */
export function can(
	decisions: AuthorizationDecisionSet | null | undefined,
	action: AuthorizationAction,
	relation?: string
): boolean {
	if (!decisions?.allowed.includes(action)) return false;
	if (relation === undefined) return true;
	const constrainedRelations = decisions.relations?.[action];
	return constrainedRelations === undefined || constrainedRelations.includes(relation);
}

/** Whether the server projected at least one concrete action for this surface. */
export function hasAllowedAction(decisions: AuthorizationDecisionSet | null | undefined): boolean {
	return Boolean(decisions?.allowed.length);
}
