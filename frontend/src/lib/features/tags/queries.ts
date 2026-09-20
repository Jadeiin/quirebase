import { queryOptions } from '@tanstack/svelte-query';
import { apiRequest } from '$lib/api/client';

export const tagKeys = {
	all: ['tags'] as const
};

export function tagsQuery() {
	return queryOptions({
		queryKey: tagKeys.all,
		queryFn: ({ signal }) => apiRequest('GET', '/tags', { signal })
	});
}
