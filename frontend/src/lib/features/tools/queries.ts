import { queryOptions } from '@tanstack/svelte-query';
import { createWorkspaceApi } from '$lib/api/client';
import { workspaceKeys } from '$lib/workspaces/keys';

export const toolKeys = {
	all: (workspaceId: string) => [...workspaceKeys.root(workspaceId), 'tools'] as const,
	duplicates: (workspaceId: string, mode: string) =>
		[...toolKeys.all(workspaceId), 'duplicates', mode] as const,
	citationStyles: (workspaceId: string, query: string) =>
		[...toolKeys.all(workspaceId), 'citation-styles', query] as const
};

export function duplicateScanQuery(workspaceId: string, mode: string) {
	const api = createWorkspaceApi(workspaceId);
	return queryOptions({
		queryKey: toolKeys.duplicates(workspaceId, mode),
		enabled: Boolean(mode),
		queryFn: ({ signal }) =>
			api.request('GET', '/workspaces/{workspace_id}/duplicates', {
				params: { query: { mode } },
				signal
			})
	});
}

export function citationStylesQuery(workspaceId: string, query: string) {
	const api = createWorkspaceApi(workspaceId);
	return queryOptions({
		queryKey: toolKeys.citationStyles(workspaceId, query),
		queryFn: ({ signal }) =>
			api.request('GET', '/workspaces/{workspace_id}/citation-styles', {
				params: { query: { query, limit: 50 } },
				signal
			})
	});
}
