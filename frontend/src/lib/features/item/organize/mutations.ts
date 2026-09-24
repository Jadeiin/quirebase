import { mutationOptions, type QueryClient } from '@tanstack/svelte-query';
import { createWorkspaceApi } from '$lib/api/client';
import { invalidateItemOrganize } from '$lib/query/invalidation';
import { workspaceKeys } from '$lib/workspaces/keys';
import type { OrganizeView } from '../types';

export type ProjectAssignmentMutation = {
	project: OrganizeView['projects'][number];
};

export type AddTagMutation = {
	form: HTMLFormElement;
	name: string;
};

export type ToggleTagMutation = {
	tagId: string;
	assigned: boolean;
};

export type SuggestedTagMutation = {
	name: string;
};

type TagTracker = (workflowId: string) => Promise<unknown>;

export function projectAssignmentMutationOptions(
	workspaceId: string,
	itemId: string,
	queryClient: QueryClient
) {
	const api = createWorkspaceApi(workspaceId);
	return mutationOptions({
		mutationKey: workspaceKeys.mutation(workspaceId, 'item-project-assignment', itemId),
		mutationFn: ({ project }: ProjectAssignmentMutation) =>
			project.assigned
				? api.request(
						'DELETE',
						'/workspaces/{workspace_id}/projects/{project_id}/items/{item_id}',
						{
							params: { path: { project_id: project.id, item_id: itemId } }
						}
					)
				: api.request('PUT', '/workspaces/{workspace_id}/projects/{project_id}/items/{item_id}', {
						params: { path: { project_id: project.id, item_id: itemId } }
					}),
		onSuccess: () => invalidateItemOrganize(queryClient, workspaceId, itemId)
	});
}

export function addTagMutationOptions(
	workspaceId: string,
	itemId: string,
	queryClient: QueryClient
) {
	const api = createWorkspaceApi(workspaceId);
	return mutationOptions({
		mutationKey: workspaceKeys.mutation(workspaceId, 'item-add-tag', itemId),
		mutationFn: ({ name }: AddTagMutation) =>
			api.request('POST', '/workspaces/{workspace_id}/items/{item_id}/tags', {
				params: { path: { item_id: itemId } },
				body: { name }
			}),
		onSuccess: async (_saved, { form }) => {
			form.reset();
			await invalidateItemOrganize(queryClient, workspaceId, itemId);
		}
	});
}

export function toggleTagMutationOptions(
	workspaceId: string,
	itemId: string,
	queryClient: QueryClient
) {
	const api = createWorkspaceApi(workspaceId);
	return mutationOptions({
		mutationKey: workspaceKeys.mutation(workspaceId, 'item-toggle-tag', itemId),
		mutationFn: ({ tagId, assigned }: ToggleTagMutation) =>
			api.request('PUT', '/workspaces/{workspace_id}/items/{item_id}/tags', {
				params: { path: { item_id: itemId } },
				body: {
					add_tag_ids: assigned ? [] : [tagId],
					remove_tag_ids: assigned ? [tagId] : [],
					new_names: []
				}
			}),
		onSuccess: () => invalidateItemOrganize(queryClient, workspaceId, itemId)
	});
}

export function suggestedTagMutationOptions(
	workspaceId: string,
	itemId: string,
	queryClient: QueryClient
) {
	const api = createWorkspaceApi(workspaceId);
	return mutationOptions({
		mutationKey: workspaceKeys.mutation(workspaceId, 'item-suggested-tag', itemId),
		mutationFn: ({ name }: SuggestedTagMutation) =>
			api.request('PUT', '/workspaces/{workspace_id}/items/{item_id}/tags', {
				params: { path: { item_id: itemId } },
				body: { add_tag_ids: [], remove_tag_ids: [], new_names: [name] }
			}),
		onSuccess: () => invalidateItemOrganize(queryClient, workspaceId, itemId)
	});
}

export function tagRecommendationsMutationOptions(
	workspaceId: string,
	itemId: string,
	queryClient: QueryClient,
	trackRecommendations: TagTracker
) {
	const api = createWorkspaceApi(workspaceId);
	return mutationOptions({
		mutationKey: workspaceKeys.mutation(workspaceId, 'item-tag-recommendations', itemId),
		mutationFn: async () => {
			const workflow = await api.request(
				'POST',
				'/workspaces/{workspace_id}/items/{item_id}/tag-recommendations',
				{
					params: { path: { item_id: itemId } }
				}
			);
			await trackRecommendations(workflow.id);
		},
		onSuccess: () => invalidateItemOrganize(queryClient, workspaceId, itemId)
	});
}
