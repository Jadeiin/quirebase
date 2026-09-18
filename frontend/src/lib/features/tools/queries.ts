import { queryOptions } from '@tanstack/svelte-query';
import { apiRequest } from '$lib/api/client';

export const toolKeys = {
	all: ['tools'] as const,
	duplicates: (mode: string) => [...toolKeys.all, 'duplicates', mode] as const,
	citationStyles: (query: string) => [...toolKeys.all, 'citation-styles', query] as const
};

export function duplicateScanQuery(mode: string) {
	return queryOptions({
		queryKey: toolKeys.duplicates(mode),
		enabled: Boolean(mode),
		queryFn: ({ signal }) =>
			apiRequest('GET', '/duplicates', { params: { query: { mode } }, signal })
	});
}

export function citationStylesQuery(query: string) {
	return queryOptions({
		queryKey: toolKeys.citationStyles(query),
		queryFn: ({ signal }) =>
			apiRequest('GET', '/citation-styles', {
				params: { query: { query, limit: 50 } },
				signal
			})
	});
}
