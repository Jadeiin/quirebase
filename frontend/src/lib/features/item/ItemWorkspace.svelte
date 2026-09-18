<script lang="ts">
	import { resolve } from '$app/paths';
	import { createMutation, createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { apiDownloadGet } from '$lib/api/client';
	import { apiErrorMessage } from '$lib/api/errors';
	import type { components } from '$lib/api/schema';
	import ConfirmDialog from '$lib/design/ConfirmDialog.svelte';
	import Notice from '$lib/design/Notice.svelte';
	import RichText from '$lib/design/RichText.svelte';
	import { getWorkflowCenter } from '$lib/features/workflows/center.svelte';
	import ItemActions from '$lib/features/item/ItemActions.svelte';
	import ItemAnnotationsSection from '$lib/features/item/annotations/ItemAnnotationsSection.svelte';
	import ItemDiscussionSection from '$lib/features/item/discussion/ItemDiscussionSection.svelte';
	import {
		discussionCreateMutationOptions,
		discussionDeleteMutationOptions
	} from '$lib/features/item/discussion/mutations';
	import ItemFilesSection from '$lib/features/item/files/ItemFilesSection.svelte';
	import {
		fileDeleteMutationOptions,
		fileRemoteUploadMutationOptions,
		fileUploadMutationOptions
	} from '$lib/features/item/files/mutations';
	import ItemMetadataSection from '$lib/features/item/metadata/ItemMetadataSection.svelte';
	import { metadataMutationOptions } from '$lib/features/item/metadata/mutations';
	import ItemOrganizeSection from '$lib/features/item/organize/ItemOrganizeSection.svelte';
	import {
		addTagMutationOptions,
		projectMembershipMutationOptions,
		suggestedTagMutationOptions,
		tagRecommendationsMutationOptions,
		toggleTagMutationOptions
	} from '$lib/features/item/organize/mutations';
	import ItemOverviewSection from '$lib/features/item/overview/ItemOverviewSection.svelte';
	import {
		itemDetailsQuery,
		itemDiscussionQuery,
		itemFilesQuery,
		itemKeys,
		itemOrganizeQuery,
		itemWorkspaceQuery,
		type ItemSection
	} from '$lib/features/item/queries';
	import type { FileRow, ItemDetail, OrganizeView } from '$lib/features/item/types';
	import { msg, t, type MessageKey } from '$lib/i18n';
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
	const title = $derived(
		(section === 'metadata' ? details.data?.title_html : undefined) ??
			(section === 'organize' ? organize.data?.item.title_html : undefined) ??
			workspace.data?.item.title_html
	);
	const labels: Record<ItemSection, MessageKey> = {
		overview: msg('Overview'),
		metadata: msg('Metadata'),
		files: msg('Files'),
		organize: msg('Organize'),
		annotations: msg('Annotations'),
		discussion: msg('Discussion')
	};
	function sectionPath(key: string) {
		return key === 'overview' ? (`/item/${itemId}` as const) : (`/item/${itemId}/${key}` as const);
	}
	const sectionLabel = $derived(labels[section as ItemSection]);

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
		return Promise.all([
			queryClient.invalidateQueries({ queryKey: itemKeys.workspace(itemId) }),
			queryClient.invalidateQueries({ queryKey: itemKeys.detail(itemId) })
		]);
	}
</script>

<div class="mb-6 flex flex-wrap items-end justify-between gap-4">
	<div class="min-w-0">
		<a
			class="mb-2 inline-flex items-center gap-1 text-xs font-bold tracking-[0.1em] text-primary-700-300 uppercase no-underline hover:text-primary-800-200"
			href={resolve('/library')}>{$t('Library')}</a
		>
		<h1 class="max-w-4xl text-balance">
			{#if title}<RichText html={title} />{:else}{$t('Item workspace')}{/if}
		</h1>
		{#if workspace.data}<p class="mt-2 text-sm text-surface-700-300">
				{workspace.data.item.authors ||
					$t('Unknown authors')}{#if workspace.data.item.publication_title}
					· {workspace.data.item.publication_title}{/if}{#if workspace.data.item.publication_date}
					· {workspace.data.item.publication_date}{/if}
			</p>{/if}
	</div>
	{#if workspace.data && session.data?.user}{#key itemId}<ItemActions
				{itemId}
				workspace={workspace.data}
				userId={session.data.user.id}
				onchanged={refetchItem}
			/>{/key}{/if}
</div>
<nav
	class="mb-6 flex gap-1 overflow-x-auto border-b border-surface-300-700"
	aria-label={$t('Item workspace')}
>
	{#each Object.entries(labels) as [key, label] (key)}<a
			class="border-b-2 border-transparent px-3 py-2.5 text-sm font-semibold whitespace-nowrap text-surface-700-300 no-underline transition-colors hover:text-primary-700-300 aria-[current=page]:border-primary-700-300 aria-[current=page]:text-primary-700-300"
			aria-current={section === key ? 'page' : undefined}
			href={resolve(sectionPath(key))}>{$t(label)}</a
		>{/each}
</nav>
{#if mutationError}<Notice variant="error">{mutationError}</Notice>{/if}
<ConfirmDialog
	bind:open={confirmFileOpen}
	title={$t('Delete this file permanently?')}
	body={pendingFile?.original_name ?? ''}
	confirmLabel={$t('Delete permanently')}
	busy={fileDelete.isPending}
	onConfirm={confirmDeleteFile}
/>
{#if (section === 'overview' && workspace.isPending) || (section === 'metadata' && details.isPending) || (section === 'files' && (files.isPending || details.isPending)) || (section === 'organize' && organize.isPending) || (section === 'discussion' && discussion.isPending)}<div
		class="grid min-h-52 grid-cols-1 place-items-center text-surface-600-400"
	>
		{$t('Loading')}
		{$t(sectionLabel).toLowerCase()}…
	</div>
{:else if (section === 'overview' && workspace.isError) || (section === 'metadata' && details.isError) || (section === 'files' && (files.isError || details.isError)) || (section === 'organize' && organize.isError) || (section === 'discussion' && discussion.isError)}<div
		class="grid min-h-52 grid-cols-1 place-items-center text-error-700-300"
	>
		{$t('Unable to open this Item section.')}
	</div>
{:else}
	{#if section === 'overview'}
		<ItemOverviewSection {itemId} data={workspace.data!} details={details.data} />
	{:else if section === 'metadata'}
		<ItemMetadataSection
			item={details.data!}
			canEdit={workspace.data?.permissions.edit ?? false}
			busy={metadataBusy}
			onSubmit={updateMetadata}
		/>
	{:else if section === 'files'}
		<ItemFilesSection
			{itemId}
			data={files.data!}
			details={details.data}
			canEdit={workspace.data?.permissions.edit ?? false}
			busy={filesBusy}
			onUpload={upload}
			onUploadFromUrl={uploadFromUrl}
			onDownload={downloadFile}
			onDelete={deleteFile}
		/>
	{:else if section === 'organize'}
		<ItemOrganizeSection
			data={organize.data!}
			busy={organizeBusy}
			onToggleProject={toggleProject}
			onAddTag={addTag}
			onToggleTag={toggleTagAssignment}
			onAddSuggestedTag={addSuggestedTag}
			onRefresh={refreshTagRecommendations}
		/>
	{:else if section === 'annotations'}
		<ItemAnnotationsSection {itemId} />
	{:else}
		<ItemDiscussionSection
			messages={discussion.data!}
			userId={session.data?.user?.id}
			isAdministrator={session.data?.user?.role === 'administrator'}
			busy={discussionBusy}
			onAdd={addDiscussion}
			onDelete={deleteDiscussion}
		/>
	{/if}
{/if}
