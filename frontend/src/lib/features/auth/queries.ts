import { queryOptions } from '@tanstack/svelte-query';
import { ApiError, apiRequest } from '$lib/api/client';

export const invitationKeys = {
	all: ['invitation'] as const,
	detail: (token: string) => [...invitationKeys.all, token] as const
};

export function invitationQuery(token: string) {
	return queryOptions({
		queryKey: invitationKeys.detail(token),
		queryFn: async ({ signal }) => {
			try {
				const invitation = await apiRequest('GET', '/invitations/{token}', {
					params: { path: { token } },
					signal
				});
				return { kind: 'account' as const, invitation };
			} catch (reason) {
				if (!(reason instanceof ApiError) || reason.status !== 404) throw reason;
			}

			const invitation = await apiRequest('GET', '/workspace-invitations/{token}', {
				params: { path: { token } },
				signal
			});
			return { kind: 'workspace' as const, invitation };
		},
		retry: false
	});
}
