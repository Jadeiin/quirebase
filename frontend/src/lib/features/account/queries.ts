import { queryOptions } from '@tanstack/svelte-query';
import { apiRequest } from '$lib/api/client';

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
	citationStyles: (query: string, include: string) =>
		[...exportPreferenceKeys.all, 'citation-styles', query, include] as const,
	citationKeyPreview: (formula: string, forceAscii: boolean) =>
		[...exportPreferenceKeys.all, 'citation-key-preview', formula, forceAscii] as const
};

export function exportCitationStylesQuery(query: string, include: string) {
	return queryOptions({
		queryKey: exportPreferenceKeys.citationStyles(query, include),
		queryFn: ({ signal }) =>
			apiRequest('GET', '/citation-styles', {
				params: { query: { query, limit: 30, include } },
				signal
			})
	});
}

export function citationKeyPreviewQuery(formula: string, forceAscii: boolean, enabled: boolean) {
	return queryOptions({
		queryKey: exportPreferenceKeys.citationKeyPreview(formula, forceAscii),
		enabled,
		queryFn: async ({ signal }) => ({
			...(await apiRequest('GET', '/citation-key-preview', {
				params: { query: { formula, force_ascii: forceAscii } },
				signal
			})),
			formula,
			forceAscii
		})
	});
}
