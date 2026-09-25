<script lang="ts">
	import { createMutation, createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { createWorkspaceApi, isDownloadCancelled } from '$lib/api/client';
	import { apiErrorMessage } from '$lib/api/errors';
	import ConfirmDialog from '$lib/design/ConfirmDialog.svelte';
	import Notice from '$lib/design/Notice.svelte';
	import {
		fileDeleteMutationOptions,
		fileRemoteUploadMutationOptions,
		fileUploadMutationOptions
	} from '$lib/features/item/files/mutations';
	import ItemFilesSection from '$lib/features/item/files/ItemFilesSection.svelte';
	import ItemSectionState from '$lib/features/item/ItemSectionState.svelte';
	import { itemDetailsQuery, itemFilesQuery, itemOverviewQuery } from '$lib/features/item/queries';
	import type { FileRow } from '$lib/features/item/types';
	import { getWorkflowCenter } from '$lib/features/workflows/center.svelte';
	import { msg, t } from '$lib/i18n';
	import type { PageProps } from './$types';
	import { getWorkspaceContext } from '$lib/workspaces/context.svelte';

	let { params }: PageProps = $props();
	let mutationError = $state('');
	let pendingFile = $state<FileRow | null>(null);
	let confirmFileOpen = $state(false);
	const queryClient = useQueryClient();
	const workspace = getWorkspaceContext();
	const workflows = getWorkflowCenter();
	const workspaceApi = $derived(createWorkspaceApi(params.workspaceId));
	const overview = createQuery(() => itemOverviewQuery(params.workspaceId, params.itemId));
	const details = createQuery(() => itemDetailsQuery(params.workspaceId, params.itemId, true));
	const files = createQuery(() => itemFilesQuery(params.workspaceId, params.itemId, true));

	async function trackDocument(workflowId: string) {
		await workflows.track(workflowId, {
			workspaceId: params.workspaceId,
			label: $t('Document processing'),
			successMessage: msg('Document processing completed'),
			failureMessage: msg('Document processing failed')
		}).settled;
	}

	const fileUpload = createMutation(() =>
		fileUploadMutationOptions(params.workspaceId, params.itemId, queryClient, trackDocument)
	);
	const fileRemoteUpload = createMutation(() =>
		fileRemoteUploadMutationOptions(params.workspaceId, params.itemId, queryClient, trackDocument)
	);
	const fileDelete = createMutation(() =>
		fileDeleteMutationOptions(params.workspaceId, params.itemId, queryClient)
	);

	function track(promise: Promise<unknown>) {
		mutationError = '';
		void promise.catch((error) => {
			if (isDownloadCancelled(error)) return;
			mutationError = apiErrorMessage(error, $t('Unable to save changes'));
		});
	}

	function upload(event: SubmitEvent, kind: 'revision' | 'attachment') {
		event.preventDefault();
		const form = event.currentTarget as HTMLFormElement;
		track(fileUpload.mutateAsync({ form, kind }));
	}

	function uploadFromUrl(event: SubmitEvent, kind: 'revision' | 'attachment') {
		event.preventDefault();
		const form = event.currentTarget as HTMLFormElement;
		track(fileRemoteUpload.mutateAsync({ form, kind }));
	}

	function downloadFile(file: FileRow) {
		if (!workspace.can('workspace.export')) return;
		track(
			file.kind === 'revision'
				? workspaceApi.downloadGet(
						'/workspaces/{workspace_id}/items/{item_id}/revisions/{revision_id}/content',
						{
							params: { path: { item_id: params.itemId, revision_id: file.id } }
						},
						{ suggestedName: file.original_name }
					)
				: workspaceApi.downloadGet(
						'/workspaces/{workspace_id}/items/{item_id}/attachments/{attachment_id}/content',
						{
							params: { path: { item_id: params.itemId, attachment_id: file.id } }
						},
						{ suggestedName: file.original_name }
					)
		);
	}

	function deleteFile(file: FileRow) {
		pendingFile = file;
		confirmFileOpen = true;
	}

	function confirmDeleteFile() {
		const file = pendingFile;
		pendingFile = null;
		confirmFileOpen = false;
		if (!file) return;
		track(fileDelete.mutateAsync({ file }));
	}
</script>

{#if mutationError}<Notice variant="error">{mutationError}</Notice>{/if}
<ConfirmDialog
	bind:open={confirmFileOpen}
	title={$t('Delete this file permanently?')}
	body={pendingFile?.original_name ?? ''}
	confirmLabel={$t('Delete permanently')}
	busy={fileDelete.isPending}
	onConfirm={confirmDeleteFile}
/>
<ItemSectionState
	loading={files.isPending || details.isPending}
	failed={files.isError || details.isError}
>
	<ItemFilesSection
		itemId={params.itemId}
		data={files.data!}
		details={details.data}
		canEdit={(overview.data?.allowed_actions.edit ?? false) && workspace.can('files.manage')}
		busy={fileUpload.isPending || fileRemoteUpload.isPending || fileDelete.isPending}
		onUpload={upload}
		onUploadFromUrl={uploadFromUrl}
		onDownload={downloadFile}
		onDelete={deleteFile}
	/>
</ItemSectionState>
