import { queryOptions } from '@tanstack/svelte-query';
import { createWorkspaceApi } from '$lib/api/client';
import { workspaceKeys } from '$lib/workspaces/keys';

export const tagKeys = {
	all: (workspaceId: string) => [...workspaceKeys.root(workspaceId), 'tags'] as const
};

export function tagsQuery(workspaceId: string) {
	const api = createWorkspaceApi(workspaceId);
	return queryOptions({
		queryKey: tagKeys.all(workspaceId),
		queryFn: ({ signal }) => api.request('GET', '/workspaces/{workspace_id}/tags', { signal })
	});
}
