import type { QueryClient } from '@tanstack/svelte-query';
import { invalidateWorkspaces } from '#lib/query/invalidation.js';
import { workspaceKeys } from '#lib/workspaces/keys.js';
import { receivedInvitationKeys } from './received-invitations.js';

/** Reconcile confirmed access loss after navigating away from this Workspace. */
export async function reconcileWorkspaceAccessLoss(
	client: QueryClient,
	workspaceId: string,
	userId: string
) {
	const scope = { queryKey: workspaceKeys.root(workspaceId) };
	await client.cancelQueries(scope);
	client.removeQueries(scope);
	await Promise.all([
		invalidateWorkspaces(client),
		client.invalidateQueries({ queryKey: receivedInvitationKeys.all(userId) })
	]);
}
