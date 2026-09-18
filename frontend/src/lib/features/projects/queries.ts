import { queryOptions } from '@tanstack/svelte-query';
import { apiRequest } from '$lib/api/client';

export const projectKeys = {
	all: ['projects'] as const,
	lists: () => [...projectKeys.all, 'list'] as const,
	joinable: () => [...projectKeys.all, 'joinable'] as const,
	detail: (projectId: string) => [...projectKeys.all, 'detail', projectId] as const
};

export function projectListQuery() {
	return queryOptions({
		queryKey: projectKeys.lists(),
		queryFn: ({ signal }) => apiRequest('GET', '/projects', { signal })
	});
}

export function joinableProjectsQuery() {
	return queryOptions({
		queryKey: projectKeys.joinable(),
		queryFn: ({ signal }) => apiRequest('GET', '/projects/joinable', { signal })
	});
}

export function projectDetailQuery(projectId: string) {
	return queryOptions({
		queryKey: projectKeys.detail(projectId),
		queryFn: ({ signal }) =>
			apiRequest('GET', '/projects/{project_id}', {
				params: { path: { project_id: projectId } },
				signal
			})
	});
}
