import { mutationOptions, type QueryClient } from '@tanstack/svelte-query';
import { apiRequest } from '$lib/api/client';
import { invalidateItemDiscussion } from '$lib/query/invalidation';

export type DiscussionCreateMutation = {
	form: HTMLFormElement;
	body: string;
};

export type DiscussionDeleteMutation = {
	messageId: string;
};

export function discussionCreateMutationOptions(itemId: string, queryClient: QueryClient) {
	return mutationOptions({
		mutationKey: ['item-discussion-create', itemId],
		mutationFn: ({ body }: DiscussionCreateMutation) =>
			apiRequest('POST', '/items/{item_id}/discussions', {
				params: { path: { item_id: itemId } },
				body: { body }
			}),
		onSuccess: async (_saved, { form }) => {
			form.reset();
			await invalidateItemDiscussion(queryClient, itemId);
		}
	});
}

export function discussionDeleteMutationOptions(itemId: string, queryClient: QueryClient) {
	return mutationOptions({
		mutationKey: ['item-discussion-delete', itemId],
		mutationFn: ({ messageId }: DiscussionDeleteMutation) =>
			apiRequest('DELETE', '/items/{item_id}/discussions/{message_id}', {
				params: { path: { item_id: itemId, message_id: messageId } }
			}),
		onSuccess: () => invalidateItemDiscussion(queryClient, itemId)
	});
}
