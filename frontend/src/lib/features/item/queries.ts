import { queryOptions } from '@tanstack/svelte-query';
import { createWorkspaceApi, type ItemOverviewView } from '$lib/api/client';
import { workspaceKeys } from '$lib/workspaces/keys';

export type ItemSection =
	'overview' | 'metadata' | 'files' | 'organize' | 'annotations' | 'discussion';

export const itemKeys = {
	all: (workspaceId: string) => workspaceKeys.items(workspaceId),
	detail: (workspaceId: string, itemId: string) => workspaceKeys.item(workspaceId, itemId),
	overview: (workspaceId: string, itemId: string) =>
		[...itemKeys.detail(workspaceId, itemId), 'overview'] as const,
	files: (workspaceId: string, itemId: string) =>
		[...itemKeys.detail(workspaceId, itemId), 'files'] as const,
	organize: (workspaceId: string, itemId: string) =>
		[...itemKeys.detail(workspaceId, itemId), 'organize'] as const,
	discussion: (workspaceId: string, itemId: string) =>
		[...itemKeys.detail(workspaceId, itemId), 'discussion'] as const,
	annotations: (workspaceId: string, itemId: string) =>
		[...itemKeys.detail(workspaceId, itemId), 'annotations'] as const,
	annotationsReview: (workspaceId: string, itemId: string, revisionId: string, page: number) =>
		[...itemKeys.annotations(workspaceId, itemId), 'review', revisionId, page] as const
};

export function itemOverviewQuery(workspaceId: string, itemId: string) {
	const api = createWorkspaceApi(workspaceId);
	return queryOptions({
		queryKey: itemKeys.overview(workspaceId, itemId),
		queryFn: ({ signal }) =>
			api.request('GET', '/workspaces/{workspace_id}/items/{item_id}/overview', {
				params: { path: { item_id: itemId } },
				signal
			})
	});
}

export function itemDetailsQuery(workspaceId: string, itemId: string, enabled: boolean) {
	const api = createWorkspaceApi(workspaceId);
	return queryOptions({
		queryKey: itemKeys.detail(workspaceId, itemId),
		enabled,
		queryFn: ({ signal }) =>
			api.request('GET', '/workspaces/{workspace_id}/items/{item_id}', {
				params: { path: { item_id: itemId } },
				signal
			})
	});
}

export function itemFilesQuery(workspaceId: string, itemId: string, enabled = true) {
	const api = createWorkspaceApi(workspaceId);
	return queryOptions({
		queryKey: itemKeys.files(workspaceId, itemId),
		enabled,
		queryFn: ({ signal }) =>
			api.request('GET', '/workspaces/{workspace_id}/items/{item_id}/documents', {
				params: { path: { item_id: itemId } },
				signal
			})
	});
}

export function itemOrganizeQuery(workspaceId: string, itemId: string, enabled = true) {
	const api = createWorkspaceApi(workspaceId);
	return queryOptions({
		queryKey: itemKeys.organize(workspaceId, itemId),
		enabled,
		queryFn: ({ signal }) =>
			api.request('GET', '/workspaces/{workspace_id}/items/{item_id}/organize', {
				params: { path: { item_id: itemId } },
				signal
			})
	});
}

export function itemDiscussionQuery(workspaceId: string, itemId: string, enabled = true) {
	const api = createWorkspaceApi(workspaceId);
	return queryOptions({
		queryKey: itemKeys.discussion(workspaceId, itemId),
		enabled,
		queryFn: ({ signal }) =>
			api.request('GET', '/workspaces/{workspace_id}/items/{item_id}/discussions', {
				params: { path: { item_id: itemId } },
				signal
			})
	});
}

export function itemAnnotationsReviewQuery(
	workspaceId: string,
	itemId: string,
	revisionId: string,
	page: number,
	enabled: boolean
) {
	const api = createWorkspaceApi(workspaceId);
	return queryOptions({
		queryKey: itemKeys.annotationsReview(workspaceId, itemId, revisionId, page),
		enabled,
		queryFn: ({ signal }) =>
			api.request('GET', '/workspaces/{workspace_id}/items/{item_id}/annotations/review', {
				params: {
					path: { item_id: itemId },
					query: {
						page,
						revision_id: revisionId === 'all' ? undefined : revisionId
					}
				},
				signal
			})
	});
}

export type ItemOverview = ItemOverviewView;
