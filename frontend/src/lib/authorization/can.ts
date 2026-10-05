import type { components } from '#lib/api/schema.js';

export type AuthorizationAction =
	components['schemas']['WorkspaceAuthorizationView']['allowed'][number];
export type AuthorizationDecisionSet = Pick<
	components['schemas']['WorkspaceAuthorizationView'],
	'allowed' | 'relations'
>;

/** Ask for a resolved base action grant; variant grants do not imply this decision. */
export function can(
	decisions: AuthorizationDecisionSet | null | undefined,
	action: AuthorizationAction
): boolean {
	return decisions?.allowed.includes(action) === true;
}

/** Ask for an independent concrete variant grant projected by the server. */
export function canVariant(
	decisions: AuthorizationDecisionSet | null | undefined,
	action: AuthorizationAction,
	relation: string
): boolean {
	return decisions?.relations?.[action]?.includes(relation) === true;
}

/** Whether the server projected a base action or concrete variant for this surface. */
export function hasAllowedAction(decisions: AuthorizationDecisionSet | null | undefined): boolean {
	return Boolean(
		decisions?.allowed.length ||
		Object.values(decisions?.relations ?? {}).some((relations) => relations.length > 0)
	);
}
