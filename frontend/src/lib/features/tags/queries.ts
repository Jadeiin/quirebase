import { infiniteQueryOptions, queryOptions } from '@tanstack/svelte-query';
import { createWorkspaceApi } from '#lib/api/client.js';
import { workspaceKeys } from '#lib/workspaces/keys.js';

export const tagKeys = {
	all: (workspaceId: string) => [...workspaceKeys.root(workspaceId), 'tags'] as const
};

export function tagsQuery(
	workspaceId: string,
	search = '',
	offset = 0,
	limit = 25,
	tagId?: string
) {
	const api = createWorkspaceApi(workspaceId);
	return queryOptions({
		queryKey: [...tagKeys.all(workspaceId), 'list', search, offset, limit, tagId],
		queryFn: ({ signal }) =>
			api.request('GET', '/workspaces/{workspace_id}/tags', {
				params: { query: { search, offset, limit, tag_id: tagId } },
				signal
			})
	});
}

export function tagOptionsQuery(workspaceId: string, search: string) {
	return infiniteQueryOptions({
		queryKey: [...tagKeys.all(workspaceId), 'options', search],
		initialPageParam: 0,
		queryFn: ({ signal, pageParam }) => {
			const api = createWorkspaceApi(workspaceId);
			return api.request('GET', '/workspaces/{workspace_id}/tags', {
				params: { query: { search, offset: pageParam, limit: 25 } },
				signal
			});
		},
		getNextPageParam: (page) =>
			page.offset + page.limit < page.total ? page.offset + page.limit : undefined,
		select: (data) => [
			...new Map(data.pages.flatMap((page) => page.items).map((tag) => [tag.id, tag])).values()
		]
	});
}
