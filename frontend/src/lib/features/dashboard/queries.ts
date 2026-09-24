import { queryOptions } from '@tanstack/svelte-query';
import { createWorkspaceApi } from '$lib/api/client';
import { workspaceKeys } from '$lib/workspaces/keys';

export const dashboardKeys = {
	all: (workspaceId: string) => [...workspaceKeys.root(workspaceId), 'dashboard'] as const,
	overview: (workspaceId: string) => dashboardKeys.all(workspaceId)
};

export function dashboardQuery(workspaceId: string) {
	const api = createWorkspaceApi(workspaceId);
	return queryOptions({
		queryKey: dashboardKeys.overview(workspaceId),
		queryFn: ({ signal }) => api.request('GET', '/workspaces/{workspace_id}/dashboard', { signal })
	});
}
