<script lang="ts">
	import { resolve } from '$app/paths';
	import { createMutation, createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { apiDownloadGet, apiRequest } from '$lib/api/client';
	import { apiErrorMessage } from '$lib/api/errors';
	import { getSession } from '$lib/session';
	import type { components } from '$lib/api/schema';
	import ConfirmDialog from '$lib/design/ConfirmDialog.svelte';
	import RichText from '$lib/design/RichText.svelte';
	import { getWorkflowCenter } from '$lib/features/workflows/center.svelte';
	import ItemAnnotationsSection from '$lib/features/item/ItemAnnotationsSection.svelte';
	import ItemDiscussionSection from '$lib/features/item/ItemDiscussionSection.svelte';
	import ItemFilesSection from '$lib/features/item/ItemFilesSection.svelte';
	import ItemMetadataSection from '$lib/features/item/ItemMetadataSection.svelte';
	import ItemOrganizeSection from '$lib/features/item/ItemOrganizeSection.svelte';
	import ItemOverviewSection from '$lib/features/item/ItemOverviewSection.svelte';
	import { itemMutationOptions } from '$lib/features/item/mutations';
	import {
		itemDetailsQuery,
		itemDiscussionQuery,
		itemFilesQuery,
		itemKeys,
		itemMetadataQuery,
		itemOrganizeQuery,
		itemOverviewQuery,
		itemShellQuery,
		type ItemSection
	} from '$lib/features/item/queries';
	import type { FileRow, ItemDetail, OrganizeView } from '$lib/features/item/types';
	import ItemActions from '$lib/ItemActions.svelte';
	import { msg, t, type MessageKey } from '$lib/i18n';

	let { itemId, section } = $props<{ itemId: string; section: ItemSection }>();
	let mutationError = $state('');
	let pendingFile = $state<FileRow | null>(null);
	let confirmFileOpen = $state(false);
	const queryClient = useQueryClient();
	const { query: session } = getSession();
	const workflows = getWorkflowCenter();

	async function trackDocumentWorkflow(workflowId: string, label: string) {
		await workflows.track(workflowId, {
			label,
			successMessage: $t('Document processing completed'),
			failureMessage: $t('Document processing failed')
		}).settled;
	}

	const shell = createQuery(() => itemShellQuery(itemId));
	const details = createQuery(() =>
		itemDetailsQuery(itemId, section === 'overview' || section === 'files')
	);
	const overview = createQuery(() => itemOverviewQuery(itemId, section === 'overview'));
	const metadata = createQuery(() => itemMetadataQuery(itemId, section === 'metadata'));
	const files = createQuery(() => itemFilesQuery(itemId, section === 'files'));
	const organize = createQuery(() => itemOrganizeQuery(itemId, section === 'organize'));
	const discussion = createQuery(() => itemDiscussionQuery(itemId, section === 'discussion'));
	const itemMutation = createMutation(() => itemMutationOptions(itemId, queryClient));
	const busy = $derived(itemMutation.isPending);
	const title = $derived(
		(section === 'metadata' ? metadata.data?.title_html : undefined) ??
			(section === 'organize' ? organize.data?.item.title_html : undefined) ??
			shell.data?.item.title_html
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
	function refetchSection() {
		switch (section) {
			case 'overview':
				return overview.refetch();
			case 'metadata':
				return metadata.refetch();
			case 'files':
				return files.refetch();
			case 'organize':
				return organize.refetch();
			case 'discussion':
				return discussion.refetch();
			case 'annotations':
				return queryClient.invalidateQueries({
					queryKey: ['item-annotations-review', itemId]
				});
			default:
				return Promise.resolve();
		}
	}

	function mutate(operation: () => Promise<unknown>, form?: HTMLFormElement) {
		mutationError = '';
		void itemMutation.mutateAsync({ run: operation, form }).catch((error) => {
			mutationError = apiErrorMessage(error, $t('Unable to save changes'));
		});
	}

	function upload(event: SubmitEvent, kind: 'revision' | 'attachment') {
		event.preventDefault();
		const form = event.currentTarget as HTMLFormElement;
		void mutate(async () => {
			const options = {
				params: { path: { item_id: itemId } },
				body: new FormData(form)
			};
			const workflow =
				kind === 'revision'
					? await apiRequest('POST', '/items/{item_id}/revisions', options)
					: await apiRequest('POST', '/items/{item_id}/attachments', options);
			await trackDocumentWorkflow(workflow.id, $t('Document processing'));
		}, form);
	}

	function uploadFromUrl(event: SubmitEvent, kind: 'revision' | 'attachment') {
		event.preventDefault();
		const form = event.currentTarget as HTMLFormElement;
		void mutate(async () => {
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
			await trackDocumentWorkflow(workflow.id, $t('Document processing'));
		}, form);
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
		void mutate(() =>
			file.kind === 'revision'
				? apiRequest('DELETE', '/items/{item_id}/revisions/{revision_id}', {
						params: { path: { item_id: itemId, revision_id: file.id } }
					})
				: apiRequest('DELETE', '/items/{item_id}/attachments/{attachment_id}', {
						params: { path: { item_id: itemId, attachment_id: file.id } }
					})
		);
	}

	function downloadFile(file: FileRow) {
		mutationError = '';
		const download =
			file.kind === 'revision'
				? apiDownloadGet('/items/{item_id}/revisions/{revision_id}/content', {
						params: { path: { item_id: itemId, revision_id: file.id } }
					})
				: apiDownloadGet('/items/{item_id}/attachments/{attachment_id}/content', {
						params: { path: { item_id: itemId, attachment_id: file.id } }
					});
		void download.catch((error) => {
			mutationError = apiErrorMessage(error, $t('Unable to save changes'));
		});
	}

	function updateMetadata(item: ItemDetail, metadata: components['schemas']['ItemMetadata-Input']) {
		void mutate(() =>
			apiRequest('PUT', '/items/{item_id}', {
				params: { path: { item_id: itemId } },
				body: { expected_version: item.version, metadata }
			})
		);
	}

	function toggleProject(project: OrganizeView['projects'][number]) {
		void mutate(() =>
			project.assigned
				? apiRequest('DELETE', '/projects/{project_id}/items/{item_id}', {
						params: { path: { project_id: project.id, item_id: itemId } }
					})
				: apiRequest('PUT', '/projects/{project_id}/items/{item_id}', {
						params: { path: { project_id: project.id, item_id: itemId } }
					})
		);
	}

	function addTag(event: SubmitEvent) {
		event.preventDefault();
		const form = event.currentTarget as HTMLFormElement;
		const name = String(new FormData(form).get('name') ?? '').trim();
		if (name)
			void mutate(
				() =>
					apiRequest('POST', '/items/{item_id}/tags', {
						params: { path: { item_id: itemId } },
						body: { name }
					}),
				form
			);
	}

	function toggleTag(tagId: string, assigned: boolean) {
		void mutate(() =>
			apiRequest('PUT', '/items/{item_id}/tags', {
				params: { path: { item_id: itemId } },
				body: {
					add_tag_ids: assigned ? [] : [tagId],
					remove_tag_ids: assigned ? [tagId] : [],
					new_names: []
				}
			})
		);
	}

	function addSuggestedTag(name: string) {
		void mutate(() =>
			apiRequest('PUT', '/items/{item_id}/tags', {
				params: { path: { item_id: itemId } },
				body: { add_tag_ids: [], remove_tag_ids: [], new_names: [name] }
			})
		);
	}

	function refreshTagRecommendations() {
		void mutate(async () => {
			const workflow = await apiRequest('POST', '/items/{item_id}/tag-recommendations', {
				params: { path: { item_id: itemId } }
			});
			await workflows.track(workflow.id, {
				label: $t('Tag recommendation'),
				successMessage: $t('Tag recommendations updated'),
				failureMessage: $t('Tag recommendation failed')
			}).settled;
		});
	}

	function addDiscussion(event: SubmitEvent) {
		event.preventDefault();
		const form = event.currentTarget as HTMLFormElement;
		const body = String(new FormData(form).get('body') ?? '').trim();
		if (body)
			void mutate(
				() =>
					apiRequest('POST', '/items/{item_id}/discussions', {
						params: { path: { item_id: itemId } },
						body: { body }
					}),
				form
			);
	}

	function deleteDiscussion(messageId: string) {
		void mutate(() =>
			apiRequest('DELETE', '/items/{item_id}/discussions/{message_id}', {
				params: { path: { item_id: itemId, message_id: messageId } }
			})
		);
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
		{#if shell.data}<p class="mt-2 text-sm text-surface-700-300">
				{shell.data.item.authors || $t('Unknown authors')}{#if shell.data.item.publication_title}
					· {shell.data.item.publication_title}{/if}{#if shell.data.item.publication_date}
					· {shell.data.item.publication_date}{/if}
			</p>{/if}
	</div>
	{#if shell.data && session.data?.user}{#key itemId}<ItemActions
				{itemId}
				workspace={shell.data}
				userId={session.data.user.id}
				onchanged={() =>
					Promise.all([
						shell.refetch(),
						refetchSection(),
						queryClient.invalidateQueries({ queryKey: itemKeys.details(itemId) })
					])}
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
{#if mutationError}<p
		class="rounded-lg border border-error-200-800 bg-error-50-950 px-4 py-3 text-error-700-300"
		role="alert"
	>
		{mutationError}
	</p>{/if}
<ConfirmDialog
	bind:open={confirmFileOpen}
	title={$t('Delete this file permanently?')}
	body={pendingFile?.original_name ?? ''}
	confirmLabel={$t('Delete permanently')}
	{busy}
	onConfirm={confirmDeleteFile}
/>
{#if (section === 'overview' && overview.isPending) || (section === 'metadata' && metadata.isPending) || (section === 'files' && files.isPending) || (section === 'organize' && organize.isPending) || (section === 'discussion' && discussion.isPending)}<div
		class="grid min-h-52 place-items-center text-surface-600-400"
	>
		{$t('Loading')}
		{$t(sectionLabel).toLowerCase()}…
	</div>
{:else if (section === 'overview' && overview.isError) || (section === 'metadata' && metadata.isError) || (section === 'files' && files.isError) || (section === 'organize' && organize.isError) || (section === 'discussion' && discussion.isError)}<div
		class="grid min-h-52 place-items-center text-error-700-300"
	>
		{$t('Unable to open this Item section.')}
	</div>
{:else}
	{#if section === 'overview'}
		<ItemOverviewSection {itemId} data={overview.data!} details={details.data} />
	{:else if section === 'metadata'}
		<ItemMetadataSection
			item={metadata.data!}
			canEdit={shell.data?.permissions.edit ?? false}
			{busy}
			onSubmit={updateMetadata}
		/>
	{:else if section === 'files'}
		<ItemFilesSection
			{itemId}
			data={files.data!}
			details={details.data}
			canEdit={shell.data?.permissions.edit ?? false}
			{busy}
			onUpload={upload}
			onUploadFromUrl={uploadFromUrl}
			onDownload={downloadFile}
			onDelete={deleteFile}
		/>
	{:else if section === 'organize'}
		<ItemOrganizeSection
			data={organize.data!}
			{busy}
			onToggleProject={toggleProject}
			onAddTag={addTag}
			onToggleTag={toggleTag}
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
			{busy}
			onAdd={addDiscussion}
			onDelete={deleteDiscussion}
		/>
	{/if}
{/if}
