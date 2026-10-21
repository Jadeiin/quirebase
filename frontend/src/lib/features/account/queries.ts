import { infiniteQueryOptions, queryOptions } from '@tanstack/svelte-query';
import { apiRequest, createWorkspaceApi } from '#lib/api/client.js';

export const accountKeys = {
	all: ['account'] as const,
	detail: () => accountKeys.all
};

export function accountQuery() {
	return queryOptions({
		queryKey: accountKeys.detail(),
		queryFn: ({ signal }) => apiRequest('GET', '/account', { signal })
	});
}

export const exportPreferenceKeys = {
	all: ['export-preferences'] as const,
	citationStyles: (workspaceId: string, query: string) =>
		[...exportPreferenceKeys.all, 'citation-styles', workspaceId, 'options', query] as const,
	citationStyle: (workspaceId: string, key: string) =>
		[...exportPreferenceKeys.all, 'citation-styles', workspaceId, 'selected', key] as const,
	citationKeyPreview: (formula: string, forceAscii: boolean) =>
		[...exportPreferenceKeys.all, 'citation-key-preview', formula, forceAscii] as const
};

export function exportCitationStylesQuery(workspaceId: string, query: string) {
	const api = createWorkspaceApi(workspaceId);
	return infiniteQueryOptions({
		queryKey: exportPreferenceKeys.citationStyles(workspaceId, query),
		enabled: Boolean(workspaceId),
		initialPageParam: 0,
		queryFn: async ({ signal, pageParam }) => ({
			...(await api.request('GET', '/workspaces/{workspace_id}/citation-styles', {
				params: { query: { query, sort: 'name', direction: 'asc', limit: 30, offset: pageParam } },
				signal
			})),
			workspaceId,
			query
		}),
		getNextPageParam: (page) =>
			page.offset + page.limit < page.total ? page.offset + page.limit : undefined,
		select: (data) => ({
			workspaceId: data.pages[0]?.workspaceId,
			query: data.pages[0]?.query,
			items: [
				...new Map(
					data.pages.flatMap((page) => page.items).map((style) => [style.key, style])
				).values()
			]
		})
	});
}

export function exportCitationStyleQuery(workspaceId: string, key: string) {
	const api = createWorkspaceApi(workspaceId);
	return queryOptions({
		queryKey: exportPreferenceKeys.citationStyle(workspaceId, key),
		enabled: Boolean(workspaceId && key),
		queryFn: async ({ signal }) => ({
			...(await api.request('GET', '/workspaces/{workspace_id}/citation-styles', {
				params: { query: { key, limit: 1, offset: 0 } },
				signal
			})),
			workspaceId,
			key
		})
	});
}

export function citationKeyPreviewQuery(formula: string, forceAscii: boolean, enabled: boolean) {
	return queryOptions({
		queryKey: exportPreferenceKeys.citationKeyPreview(formula, forceAscii),
		enabled,
		retry: false,
		queryFn: async ({ signal }) => ({
			...(await apiRequest('GET', '/account/citation-key-preview', {
				params: { query: { formula, force_ascii: forceAscii } },
				signal
			})),
			formula,
			forceAscii
		})
	});
}
