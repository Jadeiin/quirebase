import { queryOptions } from '@tanstack/svelte-query';
import { apiRequest } from '$lib/api/client';

export const dashboardKeys = {
	all: ['dashboard'] as const,
	overview: () => dashboardKeys.all
};

export function dashboardQuery() {
	return queryOptions({
		queryKey: dashboardKeys.overview(),
		queryFn: ({ signal }) => apiRequest('GET', '/dashboard', { signal })
	});
}
