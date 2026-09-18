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
	list: (filters: LibraryFilters, page: number) => ['library', filters, page] as const,
	tags: () => ['tags'] as const,
	projects: () => ['projects'] as const
};

export function libraryListQuery(filters: LibraryFilters, page: number) {
	return queryOptions({
		queryKey: libraryKeys.list(filters, page),
		queryFn: () =>
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
				}
			})
	});
}

export function libraryTagsQuery() {
	return queryOptions({
		queryKey: libraryKeys.tags(),
		queryFn: () => apiRequest('GET', '/tags')
	});
}

export function libraryProjectsQuery() {
	return queryOptions({
		queryKey: libraryKeys.projects(),
		queryFn: () => apiRequest('GET', '/projects')
	});
}

export type LibrarySearch = components['schemas']['LibrarySearchView'];
export type LibraryTag = components['schemas']['TagView'];
export type LibraryProject = components['schemas']['ProjectSummaryView'];
