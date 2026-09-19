import { mutationOptions, type QueryClient } from '@tanstack/svelte-query';
import { apiRequest } from '$lib/api/client';
import { invalidateItemFiles } from '$lib/query/invalidation';
import type { FileRow } from '../types';

export type FileUploadMutation = {
	form: HTMLFormElement;
	kind: 'revision' | 'attachment';
};

export type FileRemoteUploadMutation = FileUploadMutation;

export type FileDeleteMutation = {
	file: FileRow;
};

type DocumentTracker = (workflowId: string) => Promise<unknown>;

export function fileUploadMutationOptions(
	itemId: string,
	queryClient: QueryClient,
	trackDocument: DocumentTracker
) {
	return mutationOptions({
		mutationKey: ['item-file-upload', itemId],
		mutationFn: async ({ form, kind }: FileUploadMutation) => {
			const options = {
				params: { path: { item_id: itemId } },
				body: new FormData(form)
			};
			const workflow =
				kind === 'revision'
					? await apiRequest('POST', '/items/{item_id}/revisions', options)
					: await apiRequest('POST', '/items/{item_id}/attachments', options);
			await trackDocument(workflow.id);
		},
		onSuccess: async (_result, { form }) => {
			form.reset();
			await invalidateItemFiles(queryClient, itemId);
		}
	});
}

export function fileRemoteUploadMutationOptions(
	itemId: string,
	queryClient: QueryClient,
	trackDocument: DocumentTracker
) {
	return mutationOptions({
		mutationKey: ['item-file-remote-upload', itemId],
		mutationFn: async ({ form, kind }: FileRemoteUploadMutation) => {
			const fields = new FormData(form);
			const source = String(fields.get('url'));
			const workflow =
				kind === 'revision'
					? await apiRequest('POST', '/items/{item_id}/revisions/remote', {
							params: { path: { item_id: itemId } },
							body: { source }
						})
					: await apiRequest('POST', '/items/{item_id}/attachments/remote', {
							params: { path: { item_id: itemId } },
							body: {
								source,
								graphical_abstract: fields.has('graphical_abstract')
							}
						});
			await trackDocument(workflow.id);
		},
		onSuccess: async (_result, { form }) => {
			form.reset();
			await invalidateItemFiles(queryClient, itemId);
		}
	});
}

export function fileDeleteMutationOptions(itemId: string, queryClient: QueryClient) {
	return mutationOptions({
		mutationKey: ['item-file-delete', itemId],
		mutationFn: ({ file }: FileDeleteMutation) =>
			file.kind === 'revision'
				? apiRequest('DELETE', '/items/{item_id}/revisions/{revision_id}', {
						params: { path: { item_id: itemId, revision_id: file.id } }
					})
				: apiRequest('DELETE', '/items/{item_id}/attachments/{attachment_id}', {
						params: { path: { item_id: itemId, attachment_id: file.id } }
					}),
		onSuccess: () => invalidateItemFiles(queryClient, itemId)
	});
}
