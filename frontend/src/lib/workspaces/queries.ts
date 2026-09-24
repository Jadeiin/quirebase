import { queryOptions } from '@tanstack/svelte-query';
import { apiRequest, createWorkspaceApi } from '$lib/api/client';
import { workspaceKeys } from '$lib/workspaces/keys';

export function workspaceListQuery() {
	return queryOptions({
		queryKey: workspaceKeys.list(),
		queryFn: ({ signal }) => apiRequest('GET', '/workspaces', { signal }),
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
		retry: false
	});
}
