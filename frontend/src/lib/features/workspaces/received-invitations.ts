import { mutationOptions, queryOptions } from '@tanstack/svelte-query';
import { apiRequest } from '#lib/api/client.js';

export const receivedInvitationKeys = {
	all: (userId: string) => ['user', userId, 'received-workspace-invitations'] as const,
	list: (userId: string, offset: number, limit: number) =>
		[...receivedInvitationKeys.all(userId), 'pending', offset, limit] as const,
	detail: (userId: string, invitationId: string) =>
		[...receivedInvitationKeys.all(userId), 'detail', invitationId] as const
};

export function receivedInvitationsQuery(userId: string, offset = 0, limit = 25) {
	return queryOptions({
		queryKey: receivedInvitationKeys.list(userId, offset, limit),
		queryFn: ({ signal }) =>
			apiRequest('GET', '/me/workspace-invitations', {
				params: { query: { offset, limit } },
				signal
			}),
		enabled: Boolean(userId),
		retry: false
	});
}

export function receivedInvitationQuery(userId: string, invitationId: string) {
	return queryOptions({
		queryKey: receivedInvitationKeys.detail(userId, invitationId),
		staleTime: 0,
		queryFn: ({ signal }) =>
			apiRequest('GET', '/me/workspace-invitations/{invitation_id}', {
				params: { path: { invitation_id: invitationId } },
				signal
			}),
		retry: false
	});
}

export function acceptReceivedInvitationMutation(userId: string) {
	return mutationOptions({
		mutationKey: [...receivedInvitationKeys.all(userId), 'accept'],
		mutationFn: (invitationId: string) =>
			apiRequest('POST', '/me/workspace-invitations/{invitation_id}/accept', {
				params: { path: { invitation_id: invitationId } }
			}),
		retry: false
	});
}
