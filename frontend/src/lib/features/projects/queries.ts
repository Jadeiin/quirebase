import { infiniteQueryOptions, queryOptions } from '@tanstack/svelte-query';
import { createWorkspaceApi } from '#lib/api/client.js';
import { workspaceKeys } from '#lib/workspaces/keys.js';

export const projectKeys = {
	all: (workspaceId: string) => workspaceKeys.projects(workspaceId),
	lists: (workspaceId: string, view: 'mine' | 'joinable' | 'all') =>
		[...projectKeys.all(workspaceId), 'list', view] as const,
	detail: (workspaceId: string, projectId: string) => workspaceKeys.project(workspaceId, projectId)
};

export function projectListQuery(
	workspaceId: string,
	view: 'mine' | 'joinable' | 'all' = 'all',
	offset = 0,
	search = ''
) {
	const api = createWorkspaceApi(workspaceId);
	return queryOptions({
		queryKey: [...projectKeys.lists(workspaceId, view), 'page', offset, search],
		queryFn: ({ signal }) =>
			api.request('GET', '/workspaces/{workspace_id}/projects', {
				params: { query: { view, limit: 25, offset, search } },
				signal
			})
	});
}

export function projectOptionsQuery(workspaceId: string) {
	const api = createWorkspaceApi(workspaceId);
	return infiniteQueryOptions({
		queryKey: [...projectKeys.all(workspaceId), 'options'],
		initialPageParam: 0,
		queryFn: ({ signal, pageParam }) =>
			api.request('GET', '/workspaces/{workspace_id}/projects', {
				params: { query: { view: 'all', limit: 25, offset: pageParam } },
				signal
			}),
		getNextPageParam: (page) =>
			page.offset + page.limit < page.total ? page.offset + page.limit : undefined,
		select: (data) => [
			...new Map(data.pages.flatMap((page) => page.items).map((item) => [item.id, item])).values()
		]
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
