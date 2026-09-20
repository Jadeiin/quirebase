import { queryOptions } from '@tanstack/svelte-query';
import { apiRequest } from '$lib/api/client';

export const invitationKeys = {
	all: ['invitation'] as const,
	detail: (token: string) => [...invitationKeys.all, token] as const
};

export function invitationQuery(token: string) {
	return queryOptions({
		queryKey: invitationKeys.detail(token),
		queryFn: ({ signal }) =>
			apiRequest('GET', '/invitations/{token}', {
				params: { path: { token } },
				signal
			}),
		retry: false
	});
}
