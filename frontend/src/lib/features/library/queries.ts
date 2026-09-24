import { queryOptions } from '@tanstack/svelte-query';
import { createWorkspaceApi } from '$lib/api/client';
import type { components } from '$lib/api/schema';
import { workspaceKeys } from '$lib/workspaces/keys';

export type LibraryFilters = {
	query: string;
	tag: string;
	project: string;
	year: string;
	keyword: string;
	author: string;
};

export const libraryKeys = {
	all: (workspaceId: string) => workspaceKeys.items(workspaceId),
	lists: (workspaceId: string) => [...libraryKeys.all(workspaceId), 'list'] as const,
	list: (workspaceId: string, filters: LibraryFilters, page: number) =>
		[...libraryKeys.lists(workspaceId), filters, page] as const
};

export function libraryListQuery(workspaceId: string, filters: LibraryFilters, page: number) {
	const api = createWorkspaceApi(workspaceId);
	return queryOptions({
		queryKey: libraryKeys.list(workspaceId, filters, page),
		queryFn: ({ signal }) =>
			api.request('GET', '/workspaces/{workspace_id}/items', {
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
