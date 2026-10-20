import { queryOptions, type Query } from '@tanstack/svelte-query';
import { createQuerySerializer } from 'openapi-fetch';
import { ApiError, createWorkspaceApi } from '#lib/api/client.js';
import type { components } from '#lib/api/schema.js';
import { workspaceKeys } from '#lib/workspaces/keys.js';
import type { LibraryFilters } from './filters.js';

export const libraryKeys = {
	all: (workspaceId: string) => workspaceKeys.items(workspaceId),
	lists: (workspaceId: string) => [...libraryKeys.all(workspaceId), 'list'] as const,
	list: (workspaceId: string, filters: LibraryFilters, page: number, pageSize = 25) =>
		[...libraryKeys.lists(workspaceId), filters, page, pageSize] as const
};

export function libraryListQuery(
	workspaceId: string,
	filters: LibraryFilters,
	page: number,
	pageSize = 25
) {
	const api = createWorkspaceApi(workspaceId);
	return queryOptions({
		queryKey: libraryKeys.list(workspaceId, filters, page, pageSize),
		queryFn: async ({ signal, client, queryKey }): Promise<LibrarySearch | null> => {
			try {
				return await api.request('GET', '/workspaces/{workspace_id}/items', {
					// Exact filters distinguish an explicit empty value from omission.
					querySerializer: createQuerySerializer(),
					params: {
						query: {
							limit: pageSize,
							offset: (page - 1) * pageSize,
							query: filters.query || undefined,
							tag: filters.tag || undefined,
							project: filters.project || undefined,
							year: filters.year || undefined,
							keyword: filters.keyword || undefined,
							author: filters.author || undefined,
							reference_type: filters.reference_type,
							publication_title: filters.publication_title,
							keyword_exact: filters.keyword_exact,
							author_last_name: filters.author_last_name,
							author_first_name: filters.author_first_name,
							sort: filters.sort,
							direction: filters.direction,
							has_files: filters.has_files
						}
					},
					signal
				});
			} catch (reason) {
				if (reason instanceof ApiError && [401, 403, 404].includes(reason.status)) {
					// A null snapshot keeps the request error and stays empty through later transient failures.
					if (filters.project) {
						const prefix = libraryKeys.lists(workspaceId);
						const scope = {
							queryKey: prefix,
							predicate: ({ queryKey: key }: Query) =>
								(key[prefix.length] as LibraryFilters | undefined)?.project === filters.project
						};
						// Cancel older pages so their in-flight responses cannot restore denied associations.
						await client.cancelQueries(
							{
								...scope,
								predicate: (query) => scope.predicate(query) && query.queryKey !== queryKey
							},
							{ revert: false }
						);
						client.setQueriesData<LibrarySearch | null>(scope, null, { updatedAt: 0 });
					} else {
						client.setQueriesData<LibrarySearch | null>({ queryKey, exact: true }, null, {
							updatedAt: 0
						});
					}
				}
				throw reason;
			}
		}
	});
}

export type LibrarySearch = components['schemas']['OffsetPagination_ItemSearchView_'];
export type LibraryTag = components['schemas']['TagView'];
export type LibraryProject = components['schemas']['ProjectSummaryView'];
