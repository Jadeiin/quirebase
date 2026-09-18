import { queryOptions } from '@tanstack/svelte-query';
import { apiRequest } from '$lib/api/client';

export const pdfReaderKeys = {
	all: ['pdf-reader'] as const,
	viewer: (itemId: string, revisionId: string) =>
		[...pdfReaderKeys.all, itemId, revisionId] as const
};

export function pdfViewerQuery(itemId: string, revisionId: string) {
	return queryOptions({
		queryKey: pdfReaderKeys.viewer(itemId, revisionId),
		queryFn: ({ signal }) =>
			apiRequest('GET', '/items/{item_id}/revisions/{revision_id}/viewer', {
				params: { path: { item_id: itemId, revision_id: revisionId } },
				signal
			})
	});
}
