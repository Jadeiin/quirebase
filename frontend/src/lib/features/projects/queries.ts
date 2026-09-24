import { queryOptions } from '@tanstack/svelte-query';
import { createWorkspaceApi } from '$lib/api/client';
import { workspaceKeys } from '$lib/workspaces/keys';

export const projectKeys = {
	all: (workspaceId: string) => workspaceKeys.projects(workspaceId),
	lists: (workspaceId: string) => [...projectKeys.all(workspaceId), 'list'] as const,
	joinable: (workspaceId: string) => [...projectKeys.all(workspaceId), 'joinable'] as const,
	detail: (workspaceId: string, projectId: string) => workspaceKeys.project(workspaceId, projectId),
};

export function projectListQuery(workspaceId: string) {
	const api = createWorkspaceApi(workspaceId);
	return queryOptions({
		queryKey: projectKeys.lists(workspaceId),
		queryFn: ({ signal }) => api.request('GET', '/workspaces/{workspace_id}/projects', { signal })
	});
}

export function joinableProjectsQuery(workspaceId: string) {
	const api = createWorkspaceApi(workspaceId);
	return queryOptions({
		queryKey: projectKeys.joinable(workspaceId),
		queryFn: ({ signal }) =>
			api.request('GET', '/workspaces/{workspace_id}/projects/joinable', { signal })
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
