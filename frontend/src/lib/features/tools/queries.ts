import { queryOptions, skipToken } from '@tanstack/svelte-query';
import { createWorkspaceApi } from '#lib/api/client.js';
import { workspaceKeys } from '#lib/workspaces/keys.js';
import type { ToolsState } from './list-state.js';

type DuplicateMode = ToolsState['mode'];
type CitationStyleList = Pick<
	ToolsState,
	'styleQuery' | 'styleScope' | 'styleSize' | 'stylePage' | 'styleDirection'
>;

export const toolKeys = {
	all: (workspaceId: string) => [...workspaceKeys.root(workspaceId), 'tools'] as const,
	duplicates: (workspaceId: string, mode: DuplicateMode | null) =>
		[...toolKeys.all(workspaceId), 'duplicates', mode] as const,
	citationStyles: (workspaceId: string, listing: CitationStyleList) =>
		[...toolKeys.all(workspaceId), 'citation-styles', listing] as const
};

export function duplicateScanQuery(workspaceId: string, mode: DuplicateMode | null) {
	const api = createWorkspaceApi(workspaceId);
	return queryOptions({
		queryKey: toolKeys.duplicates(workspaceId, mode),
		enabled: Boolean(mode),
		queryFn:
			mode === null
				? skipToken
				: ({ signal }) =>
						api.request('GET', '/workspaces/{workspace_id}/duplicates', {
							params: { query: { mode } },
							signal
						})
	});
}

export function citationStylesQuery(workspaceId: string, listing: CitationStyleList) {
	const api = createWorkspaceApi(workspaceId);
	return queryOptions({
		queryKey: toolKeys.citationStyles(workspaceId, listing),
		queryFn: ({ signal }) =>
			api.request('GET', '/workspaces/{workspace_id}/citation-styles', {
				params: {
					query: {
						query: listing.styleQuery,
						scope: listing.styleScope,
						sort: 'name',
						direction: listing.styleDirection,
						limit: listing.styleSize,
						offset: (listing.stylePage - 1) * listing.styleSize
					}
				},
				signal
			})
	});
}
