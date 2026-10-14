import { mutationOptions, type QueryClient } from '@tanstack/svelte-query';
import { createWorkspaceApi } from '#lib/api/client.js';
import type { components } from '#lib/api/schema.js';
import { invalidateItem } from '#lib/query/invalidation.js';
import { workspaceKeys } from '#lib/workspaces/keys.js';
import type { ItemDetail } from '../types';

export type MetadataMutation = {
	item: ItemDetail;
	metadata: components['schemas']['ItemDetailView']['metadata'];
	citationKey: string;
	form?: HTMLFormElement;
};

export function metadataMutationOptions(
	workspaceId: string,
	itemId: string,
	queryClient: QueryClient
) {
	const api = createWorkspaceApi(workspaceId);
	return mutationOptions({
		mutationKey: workspaceKeys.mutation(workspaceId, 'item-metadata', itemId),
		mutationFn: ({ item, metadata, citationKey }: MetadataMutation) =>
			api.request('PUT', '/workspaces/{workspace_id}/items/{item_id}', {
				params: { path: { item_id: itemId } },
				body: { expected_version: item.version, metadata, citation_key: citationKey || null }
			}),
		onSuccess: async (_saved, { form }) => {
			form?.reset();
			await invalidateItem(queryClient, workspaceId, itemId);
		}
	});
}
