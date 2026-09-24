import { queryOptions } from '@tanstack/svelte-query';
import { createWorkspaceApi } from '$lib/api/client';
import { workspaceKeys } from '$lib/workspaces/keys';

export const pdfReaderKeys = {
	all: (workspaceId: string) => [...workspaceKeys.root(workspaceId), 'pdf-reader'] as const,
	viewer: (workspaceId: string, itemId: string, revisionId: string) =>
		[...pdfReaderKeys.all(workspaceId), itemId, revisionId] as const
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
