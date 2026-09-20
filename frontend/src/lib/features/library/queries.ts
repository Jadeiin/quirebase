import { queryOptions } from '@tanstack/svelte-query';
import { apiRequest } from '$lib/api/client';
import type { components } from '$lib/api/schema';

export type LibraryFilters = {
	query: string;
	tag: string;
	project: string;
	year: string;
	keyword: string;
	author: string;
};

export const libraryKeys = {
	all: ['library'] as const,
	lists: () => [...libraryKeys.all, 'list'] as const,
	list: (filters: LibraryFilters, page: number) => [...libraryKeys.lists(), filters, page] as const
};

export function libraryListQuery(filters: LibraryFilters, page: number) {
	return queryOptions({
		queryKey: libraryKeys.list(filters, page),
		queryFn: ({ signal }) =>
			apiRequest('GET', '/items', {
				params: {
					query: {
						page,
						query: filters.query,
						tag: filters.tag,
						project: filters.project,
						year: filters.year,
						keyword: filters.keyword,
						author: filters.author
					}
				},
				signal
			})
	});
}

export type LibrarySearch = components['schemas']['LibrarySearchView'];
export type LibraryTag = components['schemas']['TagView'];
export type LibraryProject = components['schemas']['ProjectSummaryView'];
