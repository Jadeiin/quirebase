import { infiniteQueryOptions, queryOptions } from '@tanstack/svelte-query';
import { apiRequest, createWorkspaceApi } from '#lib/api/client.js';
import { workspaceKeys } from '#lib/workspaces/keys.js';

export function workspaceListQuery(offset = 0, search = '') {
	return queryOptions({
		queryKey: [...workspaceKeys.list(), 'page', offset, search],
		queryFn: ({ signal }) =>
			apiRequest('GET', '/workspaces', {
				params: { query: { limit: 25, offset, search } },
				signal
			}),
		retry: false
	});
}

export function workspaceOptionsQuery() {
	return infiniteQueryOptions({
		queryKey: [...workspaceKeys.list(), 'options'],
		initialPageParam: 0,
		queryFn: ({ signal, pageParam }) =>
			apiRequest('GET', '/workspaces', {
				params: { query: { limit: 25, offset: pageParam } },
				signal
			}),
		getNextPageParam: (page) =>
			page.offset + page.limit < page.total ? page.offset + page.limit : undefined,
		select: (data) => [
			...new Map(data.pages.flatMap((page) => page.items).map((item) => [item.id, item])).values()
		],
		retry: false
	});
}

export function workspaceCreationAvailabilityQuery() {
	return queryOptions({
		queryKey: workspaceKeys.creationAvailability(),
		queryFn: ({ signal }) => apiRequest('GET', '/workspaces/creation-availability', { signal }),
		retry: false
	});
}

export function workspaceQuery(workspaceId: string) {
	const api = createWorkspaceApi(workspaceId);
	return queryOptions({
		queryKey: workspaceKeys.root(workspaceId),
		queryFn: ({ signal }) => api.request('GET', '/workspaces/{workspace_id}', { signal }),
		enabled: Boolean(workspaceId),
		retry: false
	});
}

export function memberOptionsQuery(workspaceId: string, search = '') {
	const api = createWorkspaceApi(workspaceId);
	return infiniteQueryOptions({
		queryKey: [...workspaceKeys.members(workspaceId), 'options', search],
		initialPageParam: 0,
		queryFn: ({ signal, pageParam }) =>
			api.request('GET', '/workspaces/{workspace_id}/members', {
				params: { query: { limit: 25, offset: pageParam, search } },
				signal
			}),
		getNextPageParam: (page) =>
			page.offset + page.limit < page.total ? page.offset + page.limit : undefined,
		select: (data) => [
			...new Map(
				data.pages.flatMap((page) => page.items).map((item) => [item.user_id, item])
			).values()
		]
	});
}
