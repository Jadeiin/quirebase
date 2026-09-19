import { queryOptions } from '@tanstack/svelte-query';
import { apiRequest } from '$lib/api/client';

export const discoveryKeys = {
	all: ['discovery'] as const,
	providers: () => [...discoveryKeys.all, 'providers'] as const
};

export function discoveryProvidersQuery() {
	return queryOptions({
		queryKey: discoveryKeys.providers(),
		queryFn: ({ signal }) => apiRequest('GET', '/discovery/providers', { signal })
	});
}
