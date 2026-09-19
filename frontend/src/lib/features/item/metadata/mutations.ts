import { mutationOptions, type QueryClient } from '@tanstack/svelte-query';
import { apiRequest } from '$lib/api/client';
import type { components } from '$lib/api/schema';
import { invalidateItem } from '$lib/query/invalidation';
import type { ItemDetail } from '../types';

export type MetadataMutation = {
	item: ItemDetail;
	metadata: components['schemas']['ItemMetadata-Input'];
	form?: HTMLFormElement;
};

export function metadataMutationOptions(itemId: string, queryClient: QueryClient) {
	return mutationOptions({
		mutationKey: ['item-metadata', itemId],
		mutationFn: ({ item, metadata }: MetadataMutation) =>
			apiRequest('PUT', '/items/{item_id}', {
				params: { path: { item_id: itemId } },
				body: { expected_version: item.version, metadata }
			}),
		onSuccess: async (_saved, { form }) => {
			form?.reset();
			await invalidateItem(queryClient, itemId);
		}
	});
}
