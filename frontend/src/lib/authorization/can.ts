import type { components } from '#lib/api/schema.js';

export type AuthorizationVariant = components['schemas']['ProjectParticipation'];

export type AuthorizationAction =
	components['schemas']['WorkspaceAuthorizationView']['allowed'][number];
export type AuthorizationDecisionSet = Pick<
	components['schemas']['WorkspaceAuthorizationView'],
	'allowed' | 'variants'
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
	variant: AuthorizationVariant
): boolean {
	return decisions?.variants?.[action]?.includes(variant) === true;
}

/** Whether the server projected a base action or concrete variant for this surface. */
export function hasAllowedAction(decisions: AuthorizationDecisionSet | null | undefined): boolean {
	return Boolean(
		decisions?.allowed.length ||
		Object.values(decisions?.variants ?? {}).some((variants) => variants.length > 0)
	);
}
