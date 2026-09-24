import { mutationOptions, type QueryClient } from '@tanstack/svelte-query';
import { createWorkspaceApi } from '$lib/api/client';
import { invalidateItemFiles } from '$lib/query/invalidation';
import { workspaceKeys } from '$lib/workspaces/keys';
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
	workspaceId: string,
	itemId: string,
	queryClient: QueryClient,
	trackDocument: DocumentTracker
) {
	const api = createWorkspaceApi(workspaceId);
	return mutationOptions({
		mutationKey: workspaceKeys.mutation(workspaceId, 'item-file-upload', itemId),
		mutationFn: async ({ form, kind }: FileUploadMutation) => {
			const options = {
				params: { path: { item_id: itemId } },
				body: new FormData(form)
			};
			const workflow =
				kind === 'revision'
					? await api.request(
							'POST',
							'/workspaces/{workspace_id}/items/{item_id}/revisions',
							options
						)
					: await api.request(
							'POST',
							'/workspaces/{workspace_id}/items/{item_id}/attachments',
							options
						);
			await trackDocument(workflow.id);
		},
		onSuccess: async (_result, { form }) => {
			form.reset();
			await invalidateItemFiles(queryClient, workspaceId, itemId);
		}
	});
}

export function fileRemoteUploadMutationOptions(
	workspaceId: string,
	itemId: string,
	queryClient: QueryClient,
	trackDocument: DocumentTracker
) {
	const api = createWorkspaceApi(workspaceId);
	return mutationOptions({
		mutationKey: workspaceKeys.mutation(workspaceId, 'item-file-remote-upload', itemId),
		mutationFn: async ({ form, kind }: FileRemoteUploadMutation) => {
			const fields = new FormData(form);
			const source = String(fields.get('url'));
			const workflow =
				kind === 'revision'
					? await api.request(
							'POST',
							'/workspaces/{workspace_id}/items/{item_id}/revisions/remote',
							{
								params: { path: { item_id: itemId } },
								body: { source }
							}
						)
					: await api.request(
							'POST',
							'/workspaces/{workspace_id}/items/{item_id}/attachments/remote',
							{
								params: { path: { item_id: itemId } },
								body: {
									source,
									graphical_abstract: fields.has('graphical_abstract')
								}
							}
						);
			await trackDocument(workflow.id);
		},
		onSuccess: async (_result, { form }) => {
			form.reset();
			await invalidateItemFiles(queryClient, workspaceId, itemId);
		}
	});
}

export function fileDeleteMutationOptions(
	workspaceId: string,
	itemId: string,
	queryClient: QueryClient
) {
	const api = createWorkspaceApi(workspaceId);
	return mutationOptions({
		mutationKey: workspaceKeys.mutation(workspaceId, 'item-file-delete', itemId),
		mutationFn: ({ file }: FileDeleteMutation) =>
			file.kind === 'revision'
				? api.request(
						'DELETE',
						'/workspaces/{workspace_id}/items/{item_id}/revisions/{revision_id}',
						{
							params: { path: { item_id: itemId, revision_id: file.id } }
						}
					)
				: api.request(
						'DELETE',
						'/workspaces/{workspace_id}/items/{item_id}/attachments/{attachment_id}',
						{
							params: { path: { item_id: itemId, attachment_id: file.id } }
						}
					),
		onSuccess: () => invalidateItemFiles(queryClient, workspaceId, itemId)
	});
}
