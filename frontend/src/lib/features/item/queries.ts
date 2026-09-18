import { queryOptions } from '@tanstack/svelte-query';
import { apiRequest } from '$lib/api/client';
import type { WorkspaceView } from '$lib/api/client';

export type ItemSection =
	'overview' | 'metadata' | 'files' | 'organize' | 'annotations' | 'discussion';

export const itemKeys = {
	all: ['items'] as const,
	detail: (itemId: string) => [...itemKeys.all, itemId] as const,
	workspace: (itemId: string) => [...itemKeys.detail(itemId), 'workspace'] as const,
	files: (itemId: string) => [...itemKeys.detail(itemId), 'files'] as const,
	organize: (itemId: string) => [...itemKeys.detail(itemId), 'organize'] as const,
	discussion: (itemId: string) => [...itemKeys.detail(itemId), 'discussion'] as const,
	annotations: (itemId: string) => [...itemKeys.detail(itemId), 'annotations'] as const,
	annotationsReview: (itemId: string, revisionId: string, page: number) =>
		[...itemKeys.annotations(itemId), 'review', revisionId, page] as const
};

export function itemWorkspaceQuery(itemId: string) {
	return queryOptions({
		queryKey: itemKeys.workspace(itemId),
		queryFn: ({ signal }) =>
			apiRequest('GET', '/items/{item_id}/workspace', {
				params: { path: { item_id: itemId } },
				signal
			})
	});
}

export function itemDetailsQuery(itemId: string, enabled: boolean) {
	return queryOptions({
		queryKey: itemKeys.detail(itemId),
		enabled,
		queryFn: ({ signal }) =>
			apiRequest('GET', '/items/{item_id}', {
				params: { path: { item_id: itemId } },
				signal
			})
	});
}

export function itemFilesQuery(itemId: string, enabled = true) {
	return queryOptions({
		queryKey: itemKeys.files(itemId),
		enabled,
		queryFn: ({ signal }) =>
			apiRequest('GET', '/items/{item_id}/documents', {
				params: { path: { item_id: itemId } },
				signal
			})
	});
}

export function itemOrganizeQuery(itemId: string, enabled = true) {
	return queryOptions({
		queryKey: itemKeys.organize(itemId),
		enabled,
		queryFn: ({ signal }) =>
			apiRequest('GET', '/items/{item_id}/organize', {
				params: { path: { item_id: itemId } },
				signal
			})
	});
}

export function itemDiscussionQuery(itemId: string, enabled = true) {
	return queryOptions({
		queryKey: itemKeys.discussion(itemId),
		enabled,
		queryFn: ({ signal }) =>
			apiRequest('GET', '/items/{item_id}/discussions', {
				params: { path: { item_id: itemId } },
				signal
			})
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
		queryFn: ({ signal }) =>
			apiRequest('GET', '/items/{item_id}/annotations/review', {
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

export type ItemWorkspace = WorkspaceView;
