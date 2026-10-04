import type { components } from '#lib/api/schema.js';

export type AuthorizationAction =
	components['schemas']['WorkspaceAuthorizationView']['allowed'][number];
export type AuthorizationDecisionSet = Pick<
	components['schemas']['WorkspaceAuthorizationView'],
	'allowed' | 'relations'
>;

/** Ask a server-authored decision set; never infer policy from roles or lifecycle in the UI. */
export function can(
	decisions: AuthorizationDecisionSet | null | undefined,
	action: AuthorizationAction
): boolean {
	return decisions?.allowed.includes(action) === true;
}

/** A concrete variant requires an explicit relation projection from the server. */
export function canVariant(
	decisions: AuthorizationDecisionSet | null | undefined,
	action: AuthorizationAction,
	relation: string
): boolean {
	return can(decisions, action) && decisions?.relations?.[action]?.includes(relation) === true;
}

/** Whether the server projected at least one concrete action for this surface. */
export function hasAllowedAction(decisions: AuthorizationDecisionSet | null | undefined): boolean {
	return Boolean(decisions?.allowed.length);
}
