import { mutationOptions, type QueryClient } from '@tanstack/svelte-query';
import { apiRequest } from '$lib/api/client';
import { itemKeys } from '../queries';
import type { OrganizeView } from '../types';

export type ProjectMembershipMutation = {
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

function invalidateOrganize(queryClient: QueryClient, itemId: string) {
	return Promise.all([
		queryClient.invalidateQueries({ queryKey: itemKeys.organize(itemId) }),
		queryClient.invalidateQueries({ queryKey: itemKeys.workspace(itemId) })
	]);
}

export function projectMembershipMutationOptions(itemId: string, queryClient: QueryClient) {
	return mutationOptions({
		mutationKey: ['item-project-membership', itemId],
		mutationFn: ({ project }: ProjectMembershipMutation) =>
			project.assigned
				? apiRequest('DELETE', '/projects/{project_id}/items/{item_id}', {
						params: { path: { project_id: project.id, item_id: itemId } }
					})
				: apiRequest('PUT', '/projects/{project_id}/items/{item_id}', {
						params: { path: { project_id: project.id, item_id: itemId } }
					}),
		onSuccess: () => invalidateOrganize(queryClient, itemId)
	});
}

export function addTagMutationOptions(itemId: string, queryClient: QueryClient) {
	return mutationOptions({
		mutationKey: ['item-add-tag', itemId],
		mutationFn: ({ name }: AddTagMutation) =>
			apiRequest('POST', '/items/{item_id}/tags', {
				params: { path: { item_id: itemId } },
				body: { name }
			}),
		onSuccess: async (_saved, { form }) => {
			form.reset();
			await invalidateOrganize(queryClient, itemId);
		}
	});
}

export function toggleTagMutationOptions(itemId: string, queryClient: QueryClient) {
	return mutationOptions({
		mutationKey: ['item-toggle-tag', itemId],
		mutationFn: ({ tagId, assigned }: ToggleTagMutation) =>
			apiRequest('PUT', '/items/{item_id}/tags', {
				params: { path: { item_id: itemId } },
				body: {
					add_tag_ids: assigned ? [] : [tagId],
					remove_tag_ids: assigned ? [tagId] : [],
					new_names: []
				}
			}),
		onSuccess: () => invalidateOrganize(queryClient, itemId)
	});
}

export function suggestedTagMutationOptions(itemId: string, queryClient: QueryClient) {
	return mutationOptions({
		mutationKey: ['item-suggested-tag', itemId],
		mutationFn: ({ name }: SuggestedTagMutation) =>
			apiRequest('PUT', '/items/{item_id}/tags', {
				params: { path: { item_id: itemId } },
				body: { add_tag_ids: [], remove_tag_ids: [], new_names: [name] }
			}),
		onSuccess: () => invalidateOrganize(queryClient, itemId)
	});
}

export function tagRecommendationsMutationOptions(
	itemId: string,
	queryClient: QueryClient,
	trackRecommendations: TagTracker
) {
	return mutationOptions({
		mutationKey: ['item-tag-recommendations', itemId],
		mutationFn: async () => {
			const workflow = await apiRequest('POST', '/items/{item_id}/tag-recommendations', {
				params: { path: { item_id: itemId } }
			});
			await trackRecommendations(workflow.id);
		},
		onSuccess: () => invalidateOrganize(queryClient, itemId)
	});
}
