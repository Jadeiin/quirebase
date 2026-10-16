import { queryOptions } from '@tanstack/svelte-query';
import { createWorkspaceApi } from '#lib/api/client.js';
import { workspaceKeys } from '#lib/workspaces/keys.js';

export const pdfReaderKeys = {
	all: (workspaceId: string) => [...workspaceKeys.root(workspaceId), 'pdf-reader'] as const,
	item: (workspaceId: string, itemId: string) =>
		[...pdfReaderKeys.all(workspaceId), itemId] as const,
	viewer: (workspaceId: string, itemId: string, revisionId: string) =>
		[...pdfReaderKeys.item(workspaceId, itemId), revisionId] as const
};

export function pdfViewerQuery(workspaceId: string, itemId: string, revisionId: string) {
	const api = createWorkspaceApi(workspaceId);
	return queryOptions({
		queryKey: pdfReaderKeys.viewer(workspaceId, itemId, revisionId),
		queryFn: ({ signal }) =>
			api.request(
				'GET',
				'/workspaces/{workspace_id}/items/{item_id}/revisions/{revision_id}/viewer',
				{
					params: { path: { item_id: itemId, revision_id: revisionId } },
					signal
				}
			)
	});
}
