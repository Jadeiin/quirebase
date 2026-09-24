import { queryOptions } from '@tanstack/svelte-query';
import { apiRequest, createWorkspaceApi } from '$lib/api/client';

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
	citationStyles: (workspaceId: string, query: string, include: string) =>
		[...exportPreferenceKeys.all, 'citation-styles', workspaceId, query, include] as const,
	citationKeyPreview: (workspaceId: string, formula: string, forceAscii: boolean) =>
		[...exportPreferenceKeys.all, 'citation-key-preview', workspaceId, formula, forceAscii] as const
};

export function exportCitationStylesQuery(workspaceId: string, query: string, include: string) {
	const api = createWorkspaceApi(workspaceId);
	return queryOptions({
		queryKey: exportPreferenceKeys.citationStyles(workspaceId, query, include),
		enabled: Boolean(workspaceId),
		queryFn: ({ signal }) =>
			api.request('GET', '/workspaces/{workspace_id}/citation-styles', {
				params: { query: { query, limit: 30, include } },
				signal
			})
	});
}

export function citationKeyPreviewQuery(
	workspaceId: string,
	formula: string,
	forceAscii: boolean,
	enabled: boolean
) {
	const api = createWorkspaceApi(workspaceId);
	return queryOptions({
		queryKey: exportPreferenceKeys.citationKeyPreview(workspaceId, formula, forceAscii),
		enabled: enabled && Boolean(workspaceId),
		queryFn: async ({ signal }) => ({
			...(await api.request('GET', '/workspaces/{workspace_id}/citation-key-preview', {
				params: { query: { formula, force_ascii: forceAscii } },
				signal
			})),
			formula,
			forceAscii
		})
	});
}
