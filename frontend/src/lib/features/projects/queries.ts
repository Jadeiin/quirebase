import { infiniteQueryOptions, queryOptions } from '@tanstack/svelte-query';
import { createWorkspaceApi } from '#lib/api/client.js';
import type { components } from '#lib/api/schema.js';
import { workspaceKeys } from '#lib/workspaces/keys.js';

export type ProjectSummary = components['schemas']['ProjectSummaryView'];

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
	search = '',
	pageSize = 25
) {
	const api = createWorkspaceApi(workspaceId);
	return queryOptions({
		queryKey: [...projectKeys.lists(workspaceId, view), 'page', offset, search, pageSize],
		queryFn: ({ signal }) =>
			api.request('GET', '/workspaces/{workspace_id}/projects', {
				params: { query: { view, limit: pageSize, offset, search } },
				signal
			})
	});
}

export function projectOptionsQuery(workspaceId: string, search = '') {
	const api = createWorkspaceApi(workspaceId);
	return infiniteQueryOptions({
		queryKey: [...projectKeys.all(workspaceId), 'options', search],
		initialPageParam: 0,
		queryFn: ({ signal, pageParam }) =>
			api.request('GET', '/workspaces/{workspace_id}/projects', {
				params: { query: { view: 'all', limit: 25, offset: pageParam, search } },
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
