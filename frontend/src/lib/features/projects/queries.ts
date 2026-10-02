import { queryOptions } from '@tanstack/svelte-query';
import { createWorkspaceApi } from '#lib/api/client.js';
import { workspaceKeys } from '#lib/workspaces/keys.js';

export const projectKeys = {
	all: (workspaceId: string) => workspaceKeys.projects(workspaceId),
	lists: (workspaceId: string, view: 'mine' | 'joinable' | 'all') =>
		[...projectKeys.all(workspaceId), 'list', view] as const,
	detail: (workspaceId: string, projectId: string) => workspaceKeys.project(workspaceId, projectId)
};

export function projectListQuery(workspaceId: string, view: 'mine' | 'joinable' | 'all' = 'all') {
	const api = createWorkspaceApi(workspaceId);
	return queryOptions({
		queryKey: projectKeys.lists(workspaceId, view),
		queryFn: ({ signal }) =>
			api.request('GET', '/workspaces/{workspace_id}/projects', {
				params: { query: { view } },
				signal
			})
	});
}

export function projectDetailQuery(workspaceId: string, projectId: string) {
	const api = createWorkspaceApi(workspaceId);
	return queryOptions({
		queryKey: projectKeys.detail(workspaceId, projectId),
		queryFn: ({ signal }) =>
			api.request('GET', '/workspaces/{workspace_id}/projects/{project_id}', {
				params: { path: { project_id: projectId } },
				signal
			})
	});
}
