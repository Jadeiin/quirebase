import { mutationOptions, type QueryClient } from '@tanstack/svelte-query';
import { apiRequest, createWorkspaceApi } from '#lib/api/client.js';
import type { components } from '#lib/api/schema.js';
import { invalidateWorkspaces } from '#lib/query/invalidation.js';
import { workspaceKeys } from '#lib/workspaces/keys.js';

export function workspaceCreationMutationOptions(client: QueryClient) {
	return mutationOptions({
		mutationKey: ['workspace-create'],
		mutationFn: (body: components['schemas']['WorkspaceCreateRequest']) =>
			apiRequest('POST', '/workspaces', { body }),
		onSuccess: () => invalidateWorkspaces(client)
	});
}

export function workspaceRenameMutationOptions(workspaceId: string, client: QueryClient) {
	const api = createWorkspaceApi(workspaceId);
	return mutationOptions({
		mutationKey: workspaceKeys.mutation(workspaceId, 'rename'),
		mutationFn: (name: string) =>
			api.request('PATCH', '/workspaces/{workspace_id}', { body: { name } }),
		onSuccess: () => invalidateWorkspaces(client)
	});
}

export function workspaceLeaveMutationOptions(workspaceId: string) {
	const api = createWorkspaceApi(workspaceId);
	return mutationOptions({
		mutationKey: workspaceKeys.mutation(workspaceId, 'leave'),
		mutationFn: (membershipId: string) =>
			api.request('POST', '/workspaces/{workspace_id}/leave', {
				body: { membership_id: membershipId }
			}),
		retry: false
	});
}

export type MemberCommand = {
	membershipId: string;
} & (
	| { action: 'role'; role: components['schemas']['WorkspaceInvitationRole'] }
	| {
			action: 'suspend' | 'reactivate' | 'terminate' | 'transfer';
	  }
);

export function workspaceMemberMutationOptions(workspaceId: string, client: QueryClient) {
	const api = createWorkspaceApi(workspaceId);
	return mutationOptions({
		mutationKey: workspaceKeys.mutation(workspaceId, 'member'),
		mutationFn: (command: MemberCommand) => {
			const params = { path: { membership_id: command.membershipId } };
			switch (command.action) {
				case 'role':
					return api.request('PUT', '/workspaces/{workspace_id}/members/{membership_id}/role', {
						params,
						body: { role: command.role }
					});
				case 'suspend':
					return api.request('POST', '/workspaces/{workspace_id}/members/{membership_id}/suspend', {
						params
					});
				case 'reactivate':
					return api.request(
						'POST',
						'/workspaces/{workspace_id}/members/{membership_id}/reactivate',
						{ params }
					);
				case 'terminate':
					return api.request('DELETE', '/workspaces/{workspace_id}/members/{membership_id}', {
						params
					});
				case 'transfer':
					return api.request('POST', '/workspaces/{workspace_id}/ownership/{membership_id}', {
						params
					});
			}
		},
		// A lost response may follow a committed command; read back without replaying it.
		onSettled: () => invalidateWorkspaces(client)
	});
}

export function workspaceInvitationMutationOptions(workspaceId: string, client: QueryClient) {
	const api = createWorkspaceApi(workspaceId);
	return mutationOptions({
		mutationKey: workspaceKeys.mutation(workspaceId, 'invitation-create'),
		mutationFn: (body: components['schemas']['WorkspaceInvitationRequest']) =>
			api.request('POST', '/workspaces/{workspace_id}/invitations', { body }),
		onSettled: () =>
			Promise.all([
				client.invalidateQueries({ queryKey: workspaceKeys.invitations(workspaceId) }),
				client.invalidateQueries({ queryKey: workspaceKeys.list() })
			])
	});
}

export function workspaceInvitationRevokeMutationOptions(workspaceId: string, client: QueryClient) {
	const api = createWorkspaceApi(workspaceId);
	return mutationOptions({
		mutationKey: workspaceKeys.mutation(workspaceId, 'invitation-revoke'),
		mutationFn: (invitationId: string) =>
			api.request('DELETE', '/workspaces/{workspace_id}/invitations/{invitation_id}', {
				params: { path: { invitation_id: invitationId } }
			}),
		onSettled: () => invalidateWorkspaces(client)
	});
}

export function workspaceLifecycleMutationOptions(workspaceId: string, client: QueryClient) {
	const api = createWorkspaceApi(workspaceId);
	return mutationOptions({
		mutationKey: workspaceKeys.mutation(workspaceId, 'lifecycle'),
		mutationFn: (action: 'archive' | 'restore' | 'delete') => {
			switch (action) {
				case 'archive':
					return api.request('POST', '/workspaces/{workspace_id}/archive');
				case 'restore':
					return api.request('POST', '/workspaces/{workspace_id}/restore');
				case 'delete':
					return api.request('DELETE', '/workspaces/{workspace_id}');
			}
		},
		onSuccess: () => invalidateWorkspaces(client)
	});
}

export function workspaceReindexMutationOptions(workspaceId: string) {
	const api = createWorkspaceApi(workspaceId);
	return mutationOptions({
		mutationKey: workspaceKeys.mutation(workspaceId, 'reindex'),
		mutationFn: () => api.request('POST', '/workspaces/{workspace_id}/maintenance/reindex')
	});
}
