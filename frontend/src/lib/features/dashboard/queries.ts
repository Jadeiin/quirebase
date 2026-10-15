import { queryOptions } from '@tanstack/svelte-query';
import { createWorkspaceApi } from '#lib/api/client.js';
import { workspaceKeys } from '#lib/workspaces/keys.js';

export const dashboardKeys = {
	all: (workspaceId: string) => [...workspaceKeys.root(workspaceId), 'dashboard'] as const,
	overview: (workspaceId: string) => dashboardKeys.all(workspaceId)
};

export function dashboardQuery(workspaceId: string) {
	const api = createWorkspaceApi(workspaceId);
	return queryOptions({
		queryKey: dashboardKeys.overview(workspaceId),
		// The dashboard aggregates read history and counts that change outside
		// local mutations, such as opening an Item recording a read.
		refetchOnMount: 'always',
		queryFn: ({ signal }) => api.request('GET', '/workspaces/{workspace_id}/dashboard', { signal })
	});
}
