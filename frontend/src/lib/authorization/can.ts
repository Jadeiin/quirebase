import type { components } from '#lib/api/schema.js';

export type AuthorizationAction =
	components['schemas']['WorkspaceAuthorizationView']['allowed'][number];
export type AuthorizationDecisionSet = Pick<
	components['schemas']['WorkspaceAuthorizationView'],
	'allowed'
>;
/** System capabilities projected for the signed-in account, such as Administration access. */
export type SystemAuthorizationDecisionSet = Pick<
	components['schemas']['SystemAuthorizationView'],
	'allowed'
>;

/** Ask for a resolved resource-action capability projected by the server. */
export function can(
	decisions: AuthorizationDecisionSet | null | undefined,
	action: AuthorizationAction
): boolean {
	return decisions?.allowed.includes(action) === true;
}

export function hasAllowedAction(
	decisions: AuthorizationDecisionSet | SystemAuthorizationDecisionSet | null | undefined
): boolean {
	return Boolean(decisions?.allowed.length);
}
