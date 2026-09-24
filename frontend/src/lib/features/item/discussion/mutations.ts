import { mutationOptions, type QueryClient } from '@tanstack/svelte-query';
import { createWorkspaceApi } from '$lib/api/client';
import { invalidateItemDiscussion } from '$lib/query/invalidation';
import { workspaceKeys } from '$lib/workspaces/keys';

export type DiscussionCreateMutation = {
	form: HTMLFormElement;
	body: string;
};

export type DiscussionDeleteMutation = {
	messageId: string;
};

export function discussionCreateMutationOptions(
	workspaceId: string,
	itemId: string,
	queryClient: QueryClient
) {
	const api = createWorkspaceApi(workspaceId);
	return mutationOptions({
		mutationKey: workspaceKeys.mutation(workspaceId, 'item-discussion-create', itemId),
		mutationFn: ({ body }: DiscussionCreateMutation) =>
			api.request('POST', '/workspaces/{workspace_id}/items/{item_id}/discussions', {
				params: { path: { item_id: itemId } },
				body: { body }
			}),
		onSuccess: async (_saved, { form }) => {
			form.reset();
			await invalidateItemDiscussion(queryClient, workspaceId, itemId);
		}
	});
}

export function discussionDeleteMutationOptions(
	workspaceId: string,
	itemId: string,
	queryClient: QueryClient
) {
	const api = createWorkspaceApi(workspaceId);
	return mutationOptions({
		mutationKey: workspaceKeys.mutation(workspaceId, 'item-discussion-delete', itemId),
		mutationFn: ({ messageId }: DiscussionDeleteMutation) =>
			api.request('DELETE', '/workspaces/{workspace_id}/items/{item_id}/discussions/{message_id}', {
				params: { path: { item_id: itemId, message_id: messageId } }
			}),
		onSuccess: () => invalidateItemDiscussion(queryClient, workspaceId, itemId)
	});
}
