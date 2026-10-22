import { queryOptions } from '@tanstack/svelte-query';
import { createWorkspaceApi } from '#lib/api/client.js';
import { workspaceKeys } from '#lib/workspaces/keys.js';
import type { SearchRequest } from './search-state.js';

export const discoveryKeys = {
	all: (workspaceId: string) => [...workspaceKeys.root(workspaceId), 'discovery'] as const,
	providers: (workspaceId: string) => [...discoveryKeys.all(workspaceId), 'providers'] as const,
	search: (workspaceId: string, request: SearchRequest | null) =>
		[...discoveryKeys.all(workspaceId), 'search', request] as const
};

export function discoveryProvidersQuery(workspaceId: string) {
	const api = createWorkspaceApi(workspaceId);
	return queryOptions({
		queryKey: discoveryKeys.providers(workspaceId),
		queryFn: ({ signal }) =>
			api.request('GET', '/workspaces/{workspace_id}/discovery/providers', { signal })
	});
}

export function discoverySearchQuery(workspaceId: string, request: SearchRequest | null) {
	const api = createWorkspaceApi(workspaceId);
	const snapshot = request
		? { ...request, clauses: request.clauses.map((clause) => ({ ...clause })) }
		: null;
	return queryOptions({
		queryKey: discoveryKeys.search(workspaceId, snapshot),
		enabled: Boolean(request),
		retry: false,
		staleTime: 5 * 60 * 1000,
		gcTime: 30 * 60 * 1000,
		refetchOnWindowFocus: false,
		refetchOnReconnect: false,
		queryFn: ({ signal }) => {
			if (!snapshot) throw new Error('No Discovery search has been submitted');
			return api.request('POST', '/workspaces/{workspace_id}/discovery/search', {
				body: snapshot,
				signal
			});
		}
	});
}
