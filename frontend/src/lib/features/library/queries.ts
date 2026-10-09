import { queryOptions } from '@tanstack/svelte-query';
import { createWorkspaceApi } from '#lib/api/client.js';
import type { components } from '#lib/api/schema.js';
import { workspaceKeys } from '#lib/workspaces/keys.js';

export type LibraryFilters = {
	query: string;
	tag: string;
	project: string;
	year: string;
	keyword: string;
	author: string;
	sort?: 'updated' | 'created' | 'title';
	has_files?: boolean;
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
						limit: 25,
						offset: (page - 1) * 25,
						query: filters.query,
						tag: filters.tag,
						project: filters.project || undefined,
						year: filters.year,
						keyword: filters.keyword,
						author: filters.author,
						sort: filters.sort,
						has_files: filters.has_files
					}
				},
				signal
			})
	});
}

export type LibrarySearch = components['schemas']['OffsetPagination_ItemSearchView_'];
export type LibraryTag = components['schemas']['TagView'];
export type LibraryProject = components['schemas']['ProjectSummaryView'];

export function librarySort(value: string | null): 'updated' | 'created' | 'title' {
	return value === 'created' || value === 'title' ? value : 'updated';
}
