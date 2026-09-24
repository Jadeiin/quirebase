import { queryOptions } from '@tanstack/svelte-query';
import { createWorkspaceApi } from '$lib/api/client';
import { workspaceKeys } from '$lib/workspaces/keys';

export const discoveryKeys = {
	all: (workspaceId: string) => [...workspaceKeys.root(workspaceId), 'discovery'] as const,
	providers: (workspaceId: string) => [...discoveryKeys.all(workspaceId), 'providers'] as const
};

export function discoveryProvidersQuery(workspaceId: string) {
	const api = createWorkspaceApi(workspaceId);
	return queryOptions({
		queryKey: discoveryKeys.providers(workspaceId),
		queryFn: ({ signal }) =>
			api.request('GET', '/workspaces/{workspace_id}/discovery/providers', { signal })
	});
}
