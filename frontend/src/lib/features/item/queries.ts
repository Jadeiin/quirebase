import { queryOptions } from '@tanstack/svelte-query';
import { apiRequest } from '$lib/api/client';

export type ItemSection =
	'overview' | 'metadata' | 'files' | 'organize' | 'annotations' | 'discussion';

export const itemKeys = {
	shell: (itemId: string) => ['item-shell', itemId] as const,
	details: (itemId: string) => ['item-details', itemId] as const,
	sections: (itemId: string) => ['item-section', itemId] as const,
	section: (itemId: string, section: ItemSection) =>
		section === 'overview'
			? (['item-shell', itemId] as const)
			: (['item-section', itemId, section] as const),
	annotationsReview: (itemId: string, revisionId: string, page: number) =>
		['item-annotations-review', itemId, revisionId, page] as const
};

export function itemShellQuery(itemId: string) {
	return queryOptions({
		queryKey: itemKeys.shell(itemId),
		queryFn: () =>
			apiRequest('GET', '/items/{item_id}/workspace', {
				params: { path: { item_id: itemId } }
			})
	});
}

export function itemDetailsQuery(itemId: string, enabled: boolean) {
	return queryOptions({
		queryKey: itemKeys.details(itemId),
		enabled,
		queryFn: () => apiRequest('GET', '/items/{item_id}', { params: { path: { item_id: itemId } } })
	});
}

export function itemSectionQuery(itemId: string, section: ItemSection) {
	return queryOptions({
		queryKey: itemKeys.section(itemId, section),
		queryFn: async (): Promise<unknown> => {
			const params = { path: { item_id: itemId } };
			switch (section) {
				case 'metadata':
					return apiRequest('GET', '/items/{item_id}', { params });
				case 'files':
					return apiRequest('GET', '/items/{item_id}/documents', { params });
				case 'organize':
					return apiRequest('GET', '/items/{item_id}/organize', { params });
				case 'discussion':
					return apiRequest('GET', '/items/{item_id}/discussions', { params });
				default:
					return apiRequest('GET', '/items/{item_id}/workspace', { params });
			}
		}
	});
}

export function itemAnnotationsReviewQuery(
	itemId: string,
	revisionId: string,
	page: number,
	enabled: boolean
) {
	return queryOptions({
		queryKey: itemKeys.annotationsReview(itemId, revisionId, page),
		enabled,
		queryFn: () =>
			apiRequest('GET', '/items/{item_id}/annotations/review', {
				params: {
					path: { item_id: itemId },
					query: {
						page,
						revision_id: revisionId === 'all' ? undefined : revisionId
					}
				}
			})
	});
}
