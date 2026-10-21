import { queryOptions, type Query, type QueryClient, type QueryKey } from '@tanstack/svelte-query';
import { createQuerySerializer } from 'openapi-fetch';
import { ApiError, createWorkspaceApi } from '#lib/api/client.js';
import type { components } from '#lib/api/schema.js';
import { workspaceKeys } from '#lib/workspaces/keys.js';
import type { LibraryFilters } from './filters.js';

export const libraryKeys = {
	all: (workspaceId: string) => workspaceKeys.items(workspaceId),
	lists: (workspaceId: string) => [...libraryKeys.all(workspaceId), 'list'] as const,
	list: (workspaceId: string, filters: LibraryFilters, page: number, pageSize = 25) =>
		[...libraryKeys.lists(workspaceId), filters, page, pageSize] as const,
	facets: (workspaceId: string, filters: LibraryFilters, page = 1, pageSize = 25) =>
		[...libraryKeys.all(workspaceId), 'facets', filters, page, pageSize] as const
};

function libraryFilterParameters(filters: LibraryFilters) {
	return {
		query: filters.query || undefined,
		tag: filters.tag || undefined,
		project: filters.project || undefined,
		import_batch: filters.import_batch || undefined,
		year: filters.year || undefined,
		keyword: filters.keyword || undefined,
		author: filters.author || undefined,
		reference_type: filters.reference_type,
		publication_title: filters.publication_title,
		keyword_exact: filters.keyword_exact,
		author_last_name: filters.author_last_name,
		author_first_name: filters.author_first_name,
		has_files: filters.has_files
	};
}

export function libraryProjectScope(workspaceId: string, projectId: string) {
	return libraryFilterScope(workspaceId, 'project', projectId);
}

export function libraryImportScope(workspaceId: string, batchId: string) {
	return libraryFilterScope(workspaceId, 'import_batch', batchId);
}

function libraryFilterScope(workspaceId: string, key: 'project' | 'import_batch', id: string) {
	const prefix = libraryKeys.all(workspaceId);
	return {
		queryKey: prefix,
		predicate: ({ queryKey }: Query) =>
			(queryKey[prefix.length] === 'list' || queryKey[prefix.length] === 'facets') &&
			(queryKey[prefix.length + 1] as LibraryFilters | undefined)?.[key] === id
	};
}

async function reconcileReadFailure(
	reason: unknown,
	client: QueryClient,
	workspaceId: string,
	filters: LibraryFilters,
	queryKey: QueryKey
) {
	if (!(reason instanceof ApiError)) return;
	const denied = [401, 403, 404].includes(reason.status);
	const batchConflict = reason.status === 409 && reason.code === 'import_batch_conflict';
	if (!denied && !batchConflict) return;
	const batchUnavailable = reason.code === 'import_batch_unavailable' || batchConflict;
	// Null remains unavailable if a later refetch pauses or fails; it is never an empty result.
	// A combined filter does not make both resources unavailable. The typed batch
	// failure takes precedence; other denials concern the selected Project.
	const scope =
		filters.import_batch && (batchUnavailable || !filters.project)
			? libraryImportScope(workspaceId, filters.import_batch)
			: denied && filters.project
				? libraryProjectScope(workspaceId, filters.project)
				: null;
	if (scope) {
		// Cancel related reads before purging so late responses cannot restore denied associations.
		await client.cancelQueries(
			{
				...scope,
				predicate: (query) => scope.predicate(query) && query.queryKey !== queryKey
			},
			{ revert: false }
		);
	}
	client.setQueriesData(scope ?? { queryKey, exact: true }, null, { updatedAt: 0 });
}

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
							...libraryFilterParameters(filters),
							limit: pageSize,
							offset: (page - 1) * pageSize,
							sort: filters.sort,
							direction: filters.direction
						}
					},
					signal
				});
			} catch (reason) {
				await reconcileReadFailure(reason, client, workspaceId, filters, queryKey);
				throw reason;
			}
		}
	});
}

export function libraryFacetsQuery(
	workspaceId: string,
	filters: LibraryFilters,
	page = 1,
	pageSize = 25
) {
	const api = createWorkspaceApi(workspaceId);
	return queryOptions({
		queryKey: libraryKeys.facets(workspaceId, filters, page, pageSize),
		queryFn: async ({ signal, client, queryKey }): Promise<LibraryFacets | null> => {
			try {
				return await api.request('GET', '/workspaces/{workspace_id}/items/facets', {
					querySerializer: createQuerySerializer(),
					params: {
						query: {
							...libraryFilterParameters(filters),
							limit: pageSize,
							offset: (page - 1) * pageSize,
							sort: filters.sort,
							direction: filters.direction
						}
					},
					signal
				});
			} catch (reason) {
				await reconcileReadFailure(reason, client, workspaceId, filters, queryKey);
				throw reason;
			}
		}
	});
}

export type LibrarySearch = components['schemas']['OffsetPagination_ItemSearchView_'];
export type LibraryFacets = components['schemas']['LibraryFacets'];
export type LibraryTag = components['schemas']['TagView'];
