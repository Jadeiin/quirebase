<script lang="ts">
	import { createMutation, createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { apiDownloadGet } from '$lib/api/client';
	import { apiErrorMessage } from '$lib/api/errors';
	import type { components } from '$lib/api/schema';
	import ConfirmDialog from '$lib/design/ConfirmDialog.svelte';
	import Notice from '$lib/design/Notice.svelte';
	import { getWorkflowCenter } from '$lib/features/workflows/center.svelte';
	import ItemWorkspaceHeader from '$lib/features/item/ItemWorkspaceHeader.svelte';
	import {
		discussionCreateMutationOptions,
		discussionDeleteMutationOptions
	} from '$lib/features/item/discussion/mutations';
	import {
		fileDeleteMutationOptions,
		fileRemoteUploadMutationOptions,
		fileUploadMutationOptions
	} from '$lib/features/item/files/mutations';
	import { metadataMutationOptions } from '$lib/features/item/metadata/mutations';
	import {
		addTagMutationOptions,
		projectMembershipMutationOptions,
		suggestedTagMutationOptions,
		tagRecommendationsMutationOptions,
		toggleTagMutationOptions
	} from '$lib/features/item/organize/mutations';
	import ItemWorkspaceContent from '$lib/features/item/ItemWorkspaceContent.svelte';
	import {
		itemDetailsQuery,
		itemDiscussionQuery,
		itemFilesQuery,
		itemOrganizeQuery,
		itemWorkspaceQuery,
		type ItemSection
	} from '$lib/features/item/queries';
	import type { FileRow, ItemDetail, OrganizeView } from '$lib/features/item/types';
	import { invalidateItem } from '$lib/query/invalidation';
	import { msg, t } from '$lib/i18n';
	import { getSession } from '$lib/session';

	let { itemId, section } = $props<{ itemId: string; section: ItemSection }>();
	let mutationError = $state('');
	let pendingFile = $state<FileRow | null>(null);
	let confirmFileOpen = $state(false);
	const queryClient = useQueryClient();
	const { query: session } = getSession();
	const workflows = getWorkflowCenter();

	async function trackDocument(workflowId: string) {
		await workflows.track(workflowId, {
			label: $t('Document processing'),
			successMessage: msg('Document processing completed'),
			failureMessage: msg('Document processing failed')
		}).settled;
	}

	async function trackTagRecommendations(workflowId: string) {
		await workflows.track(workflowId, {
			label: $t('Tag recommendation'),
			successMessage: msg('Tag recommendations updated'),
			failureMessage: msg('Tag recommendation failed')
		}).settled;
	}

	const workspace = createQuery(() => itemWorkspaceQuery(itemId));
	const details = createQuery(() =>
		itemDetailsQuery(itemId, ['overview', 'metadata', 'files'].includes(section))
	);
	const files = createQuery(() => itemFilesQuery(itemId, section === 'files'));
	const organize = createQuery(() => itemOrganizeQuery(itemId, section === 'organize'));
	const discussion = createQuery(() => itemDiscussionQuery(itemId, section === 'discussion'));

	const metadataMutation = createMutation(() => metadataMutationOptions(itemId, queryClient));
	const fileUpload = createMutation(() =>
		fileUploadMutationOptions(itemId, queryClient, trackDocument)
	);
	const fileRemoteUpload = createMutation(() =>
		fileRemoteUploadMutationOptions(itemId, queryClient, trackDocument)
	);
	const fileDelete = createMutation(() => fileDeleteMutationOptions(itemId, queryClient));
	const projectMembership = createMutation(() =>
		projectMembershipMutationOptions(itemId, queryClient)
	);
	const addTagMutation = createMutation(() => addTagMutationOptions(itemId, queryClient));
	const toggleTagMutation = createMutation(() => toggleTagMutationOptions(itemId, queryClient));
	const suggestedTagMutation = createMutation(() =>
		suggestedTagMutationOptions(itemId, queryClient)
	);
	const tagRecommendationsMutation = createMutation(() =>
		tagRecommendationsMutationOptions(itemId, queryClient, trackTagRecommendations)
	);
	const discussionCreate = createMutation(() =>
		discussionCreateMutationOptions(itemId, queryClient)
	);
	const discussionDelete = createMutation(() =>
		discussionDeleteMutationOptions(itemId, queryClient)
	);

	const metadataBusy = $derived(metadataMutation.isPending);
	const filesBusy = $derived(
		fileUpload.isPending || fileRemoteUpload.isPending || fileDelete.isPending
	);
	const organizeBusy = $derived(
		projectMembership.isPending ||
			addTagMutation.isPending ||
			toggleTagMutation.isPending ||
			suggestedTagMutation.isPending ||
			tagRecommendationsMutation.isPending
	);
	const discussionBusy = $derived(discussionCreate.isPending || discussionDelete.isPending);
	const sectionLoading = $derived(
		(section === 'overview' && workspace.isPending) ||
			(section === 'metadata' && details.isPending) ||
			(section === 'files' && (files.isPending || details.isPending)) ||
			(section === 'organize' && organize.isPending) ||
			(section === 'discussion' && discussion.isPending)
	);
	const sectionFailed = $derived(
		(section === 'overview' && workspace.isError) ||
			(section === 'metadata' && details.isError) ||
			(section === 'files' && (files.isError || details.isError)) ||
			(section === 'organize' && organize.isError) ||
			(section === 'discussion' && discussion.isError)
	);

	function track(promise: Promise<unknown>) {
		mutationError = '';
		void promise.catch((error) => {
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
		track(
			file.kind === 'revision'
				? apiDownloadGet('/items/{item_id}/revisions/{revision_id}/content', {
						params: { path: { item_id: itemId, revision_id: file.id } }
					})
				: apiDownloadGet('/items/{item_id}/attachments/{attachment_id}/content', {
						params: { path: { item_id: itemId, attachment_id: file.id } }
					})
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

	function updateMetadata(item: ItemDetail, metadata: components['schemas']['ItemMetadata-Input']) {
		track(metadataMutation.mutateAsync({ item, metadata }));
	}

	function toggleProject(project: OrganizeView['projects'][number]) {
		track(projectMembership.mutateAsync({ project }));
	}

	function addTag(event: SubmitEvent) {
		event.preventDefault();
		const form = event.currentTarget as HTMLFormElement;
		const name = String(new FormData(form).get('name') ?? '').trim();
		if (name) track(addTagMutation.mutateAsync({ form, name }));
	}

	function toggleTagAssignment(tagId: string, assigned: boolean) {
		track(toggleTagMutation.mutateAsync({ tagId, assigned }));
	}

	function addSuggestedTag(name: string) {
		track(suggestedTagMutation.mutateAsync({ name }));
	}

	function refreshTagRecommendations() {
		track(tagRecommendationsMutation.mutateAsync());
	}

	function addDiscussion(event: SubmitEvent) {
		event.preventDefault();
		const form = event.currentTarget as HTMLFormElement;
		const body = String(new FormData(form).get('body') ?? '').trim();
		if (body) track(discussionCreate.mutateAsync({ form, body }));
	}

	function deleteDiscussion(messageId: string) {
		track(discussionDelete.mutateAsync({ messageId }));
	}

	function refetchItem() {
		return invalidateItem(queryClient, itemId);
	}
</script>

<ItemWorkspaceHeader
	{itemId}
	{section}
	workspace={workspace.data}
	details={details.data}
	organize={organize.data}
	user={session.data?.user}
	onChanged={refetchItem}
/>
{#if mutationError}<Notice variant="error">{mutationError}</Notice>{/if}
<ConfirmDialog
	bind:open={confirmFileOpen}
	title={$t('Delete this file permanently?')}
	body={pendingFile?.original_name ?? ''}
	confirmLabel={$t('Delete permanently')}
	busy={fileDelete.isPending}
	onConfirm={confirmDeleteFile}
/>
<ItemWorkspaceContent
	{itemId}
	{section}
	workspace={workspace.data}
	details={details.data}
	files={files.data}
	organize={organize.data}
	discussion={discussion.data}
	loading={sectionLoading}
	failed={sectionFailed}
	canEdit={workspace.data?.permissions.edit ?? false}
	{metadataBusy}
	{filesBusy}
	{organizeBusy}
	{discussionBusy}
	onMetadata={updateMetadata}
	onUpload={upload}
	onUploadFromUrl={uploadFromUrl}
	onDownload={downloadFile}
	onDelete={deleteFile}
	onToggleProject={toggleProject}
	onAddTag={addTag}
	onToggleTag={toggleTagAssignment}
	onAddSuggestedTag={addSuggestedTag}
	onRefresh={refreshTagRecommendations}
	onAddDiscussion={addDiscussion}
	onDeleteDiscussion={deleteDiscussion}
	userId={session.data?.user?.id}
	isAdministrator={session.data?.user?.role === 'administrator'}
/>
