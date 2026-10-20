<script lang="ts">
	import SearchSelect from '#lib/design/SearchSelect.svelte';
	import { resolve } from '$app/paths';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { Dialog, Portal, Tabs } from '@skeletonlabs/skeleton-svelte';
	import { createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { onDestroy, onMount } from 'svelte';
	import { SvelteSet } from 'svelte/reactivity';
	import { ApiError, isDownloadCancelled, type ItemOverviewView } from '#lib/api/client.js';
	import { apiErrorMessage } from '#lib/api/errors.js';
	import { can } from '#lib/authorization/can.js';
	import Button from '#lib/design/Button.svelte';
	import DialogCloseButton from '#lib/design/DialogCloseButton.svelte';
	import Icon from '#lib/design/Icon.svelte';
	import Notice from '#lib/design/Notice.svelte';
	import QueryError from '#lib/design/QueryError.svelte';
	import LoadingState from '#lib/design/LoadingState.svelte';
	import { domainLabel } from '#lib/domain-labels.js';
	import {
		bibliographyExportParameters,
		bibliographyFilename,
		bibliographyFormats,
		defaultExportPreferences,
		readExportPreferences,
		type ExportPreferences
	} from '#lib/export-preferences.js';
	import { itemFilesQuery, itemMetadataSourcesQuery } from '#lib/features/item/queries.js';
	import { invalidateLibrary, invalidateProject, invalidateTags } from '#lib/query/invalidation.js';
	import { t } from '#lib/i18n.js';
	import { getWorkspaceContext } from '#lib/workspaces/context.svelte.js';
	import { workspaceHref } from '#lib/workspaces/href.js';
	import {
		libraryItemHref,
		libraryReturnHref,
		readLibraryReturnTo
	} from '#lib/features/library/return-context.js';

	type ActionSection = 'documents' | 'citation' | 'sources' | 'danger' | 'copy';

	let {
		itemId,
		overview,
		userId,
		onchanged
	}: {
		itemId: string;
		overview: ItemOverviewView;
		userId: string;
		onchanged: () => Promise<unknown>;
	} = $props();
	let open = $state(false);
	let section = $state<ActionSection>('citation');
	let busy = $state(false);
	let error = $state('');
	let notice = $state('');
	let format = $state<ExportPreferences['citation']['format']>('csl');
	let preferences = $state<ExportPreferences>(structuredClone(defaultExportPreferences));
	let doiProvider = $state('auto');
	let selectedRevisions = new SvelteSet<string>();
	let revisionSelectionInitialized = false;
	let deleteArmed = $state(false);
	const queryClient = useQueryClient();
	const workspaceContext = getWorkspaceContext();
	const { workspaceId } = workspaceContext;
	let targetWorkspaceId = $state('');
	let copiedItemUrl = $state('');
	let mounted = true;
	onDestroy(() => (mounted = false));
	const files = createQuery(() =>
		itemFilesQuery(workspaceId, itemId, open && section === 'documents')
	);
	const revisions = $derived(files.data?.files.filter((file) => file.kind === 'revision') ?? []);
	const copyDestinations = $derived(overview.copy_targets);
	const sources = createQuery(() =>
		itemMetadataSourcesQuery(workspaceId, itemId, open && section === 'sources')
	);
	const doiSource = $derived(
		sources.data?.sources.find((row) => row.namespace === 'doi' && row.providers.length)
	);
	const doiProviders = $derived(doiSource?.providers ?? []);
	$effect(() => {
		if (
			sources.data &&
			doiProvider !== 'auto' &&
			!doiProviders.some((choice) => choice.id === doiProvider)
		) {
			doiProvider = 'auto';
		}
	});
	const externalIdentifiers = $derived(
		sources.data?.sources.filter((row) => row !== doiSource) ?? []
	);

	onMount(() => {
		preferences = readExportPreferences(userId, workspaceId);
		format = preferences.citation.format;
	});

	$effect(() => {
		if (revisionSelectionInitialized || files.isPending || !files.data) return;
		revisionSelectionInitialized = true;
		for (const revision of revisions) selectedRevisions.add(revision.id);
	});

	function show(next: ActionSection) {
		section = next;
		deleteArmed = false;
		error = '';
		notice = '';
		open = true;
	}

	function bibliographyParameters() {
		return bibliographyExportParameters(preferences.citation, format);
	}

	function archiveFilename() {
		const includeAnnotations = preferences.document.includeAnnotations;
		const includeSupplements = preferences.document.includeSupplements;
		const kind =
			includeAnnotations && includeSupplements
				? 'annotated-bundle'
				: includeAnnotations
					? 'annotated-pdfs'
					: includeSupplements
						? 'bundle'
						: 'pdfs';
		return `quirebase-${kind}.zip`;
	}

	async function action(operation: () => Promise<unknown>, success: string) {
		if (busy) return;
		busy = true;
		error = '';
		notice = '';
		try {
			await operation();
			notice = success;
		} catch (reason) {
			if (isDownloadCancelled(reason)) return;
			if (reason instanceof ApiError && reason.status === 409) {
				await onchanged();
				error = $t('This Item changed. Latest state was loaded; review it and explicitly retry.');
				return;
			}
			error = apiErrorMessage(reason, $t('Item action failed'));
		} finally {
			busy = false;
		}
	}

	function downloadBibliography() {
		void action(
			() =>
				workspaceContext.api.downloadGet(
					'/workspaces/{workspace_id}/items/{item_id}/bibliography',
					{
						params: { path: { item_id: itemId }, query: bibliographyParameters() }
					},
					{ suggestedName: bibliographyFilename(format) }
				),
			$t('Bibliography downloaded')
		);
	}

	function copyBibliography() {
		void action(async () => {
			const content = await workspaceContext.api.text(
				'/workspaces/{workspace_id}/items/{item_id}/bibliography/content',
				{
					params: { path: { item_id: itemId }, query: bibliographyParameters() }
				}
			);
			await navigator.clipboard.writeText(content);
		}, $t('Copied to clipboard'));
	}

	function downloadDocuments() {
		void action(
			() =>
				workspaceContext.api.downloadGet(
					'/workspaces/{workspace_id}/items/{item_id}/archive',
					{
						params: {
							path: { item_id: itemId },
							query: {
								revisions: [...selectedRevisions].join(','),
								include_annotations: preferences.document.includeAnnotations,
								include_supplements: preferences.document.includeSupplements,
								timezone: Intl.DateTimeFormat().resolvedOptions().timeZone
							}
						}
					},
					{ suggestedName: archiveFilename() }
				),
			$t('Document bundle downloaded')
		);
	}

	function synchronize(provider: string, uid: string) {
		if (!sources.data) return;
		const expectedVersion = sources.data.version;
		void action(async () => {
			await workspaceContext.api.request(
				'POST',
				'/workspaces/{workspace_id}/items/{item_id}/metadata/sync',
				{
					params: { path: { item_id: itemId } },
					body: { expected_version: expectedVersion, provider, uid }
				}
			);
			await onchanged();
		}, $t('Metadata synchronized'));
	}

	function regenerateCitationKey() {
		void action(async () => {
			await workspaceContext.api.request(
				'POST',
				'/workspaces/{workspace_id}/items/{item_id}/citation-key/regenerate',
				{
					params: { path: { item_id: itemId } }
				}
			);
			await onchanged();
		}, $t('Citation key updated'));
	}

	function rescanDoi() {
		void action(async () => {
			await workspaceContext.api.request(
				'POST',
				'/workspaces/{workspace_id}/items/{item_id}/doi/rescan',
				{
					params: { path: { item_id: itemId } }
				}
			);
			await onchanged();
		}, $t('PDF scanned for a DOI'));
	}

	function deleteItem() {
		deleteArmed = true;
	}

	function confirmDeleteItem() {
		deleteArmed = false;
		if (!can(overview.authorization, 'item.delete')) return;
		const originUrl = page.url;
		const deletedItemId = itemId;
		const destination = libraryReturnHref(workspaceId, page.url.searchParams, {
			deletedItemId
		});
		void action(async () => {
			await workspaceContext.api.request('DELETE', '/workspaces/{workspace_id}/items/{item_id}', {
				params: { path: { item_id: deletedItemId } },
				body: { confirmation: 'delete' }
			});
			// Deletion also removes the Item from its Projects, changing their
			// counts, lists and reader sources.
			await Promise.all([
				invalidateTags(queryClient, workspaceId),
				invalidateProject(queryClient, workspaceId)
			]);
			if (mounted && page.url === originUrl) await goto(resolve(destination));
		}, $t('Item deleted'));
	}

	function copyItem() {
		if (
			!targetWorkspaceId ||
			!copyDestinations.some(
				(candidate: ItemOverviewView['copy_targets'][number]) => candidate.id === targetWorkspaceId
			)
		)
			return;
		void action(async () => {
			const copied = await workspaceContext.api.request(
				'POST',
				'/workspaces/{workspace_id}/items/{item_id}/copy',
				{
					params: { path: { item_id: itemId } },
					body: { target_workspace_id: targetWorkspaceId }
				}
			);
			await invalidateLibrary(queryClient, copied.target_workspace_id);
			copiedItemUrl = resolve(
				workspaceHref(copied.target_workspace_id, `item/${copied.target_item_id}`)
			);
		}, $t('Item copied to Workspace'));
	}
</script>

<div class="flex flex-wrap gap-2">
	{#if overview.latest_revision_id}<Button
			as="a"
			variant="filled"
			class="inline-flex items-center gap-2"
			href={resolve(
				libraryItemHref(
					workspaceId,
					itemId,
					`pdf/${overview.latest_revision_id}`,
					readLibraryReturnTo(workspaceId, page.url.searchParams)
				)
			)}>{$t('Read PDF')}</Button
		>{#if can(overview.authorization, 'workspace.export')}<Button
				class="inline-flex items-center gap-2"
				onclick={() => show('documents')}><Icon name="download" /> {$t('Download')}</Button
			>{/if}{/if}
	{#if can(overview.authorization, 'workspace.export')}<Button onclick={() => show('citation')}
			>{$t('Export')}</Button
		>{/if}
	{#if can(overview.authorization, 'item.update')}<Button onclick={() => show('sources')}
			>{$t('Record tools')}</Button
		>{/if}
	{#if copyDestinations.length}<Button variant="tonal" onclick={() => show('copy')}
			>{$t('Copy to Workspace')}</Button
		>{/if}
	{#if can(overview.authorization, 'item.delete')}<Button
			class="inline-flex items-center gap-2"
			onclick={() => show('danger')}><Icon name="more" /> {$t('More')}</Button
		>{/if}
</div>

<Dialog
	{open}
	onOpenChange={(details) => {
		if (!busy) open = details.open;
	}}
>
	<Portal>
		<Dialog.Backdrop class="fixed inset-0 z-70 bg-surface-950/45 backdrop-blur-[2px]" />
		<Dialog.Positioner class="fixed inset-0 z-71 grid grid-cols-1 place-items-center p-4">
			<Dialog.Content
				class="grid max-h-[min(46rem,calc(100dvh-2rem))] w-full max-w-3xl grid-cols-1 grid-rows-[auto_minmax(0,1fr)] overflow-hidden rounded-container border border-surface-300-700 bg-surface-50-950 shadow-2xl"
			>
				<header class="flex items-center justify-between border-b border-surface-300-700 px-5 py-4">
					<Dialog.Title class="text-lg font-bold">{$t('Item actions')}</Dialog.Title>
					<DialogCloseButton disabled={busy} />
				</header>
				<Tabs
					value={section}
					onValueChange={(details) => {
						if (!busy) section = (details.value ?? 'citation') as ActionSection;
					}}
					class="grid min-h-0 grid-cols-1 grid-rows-[auto_minmax(0,1fr)]"
				>
					<Tabs.List class="mb-0 overflow-x-auto px-3 pt-2" aria-label={$t('Item actions')}>
						<Tabs.Indicator class="bg-primary-700-300" />
						<Tabs.Trigger
							class="whitespace-nowrap data-selected:text-primary-800-200"
							value="citation">{$t('Citation')}</Tabs.Trigger
						>

						{#if copyDestinations.length}
							<Tabs.Trigger
								class="whitespace-nowrap data-selected:text-primary-800-200"
								value="copy">{$t('Copy')}</Tabs.Trigger
							>
						{/if}

						{#if overview.latest_revision_id && can(overview.authorization, 'workspace.export')}
							<Tabs.Trigger
								class="whitespace-nowrap data-selected:text-primary-800-200"
								value="documents">{$t('Documents')}</Tabs.Trigger
							>
						{/if}

						{#if can(overview.authorization, 'item.update')}
							<Tabs.Trigger
								class="whitespace-nowrap data-selected:text-primary-800-200"
								value="sources">{$t('Metadata sources')}</Tabs.Trigger
							>
						{/if}

						{#if can(overview.authorization, 'item.delete')}
							<Tabs.Trigger class="whitespace-nowrap text-error-700-300" value="danger"
								>{$t('Danger zone')}</Tabs.Trigger
							>
						{/if}
					</Tabs.List>
					<div class="overflow-auto p-5">
						{#if error}<Notice variant="error">{error}</Notice>{/if}
						{#if notice}<Notice variant="success">{notice}</Notice>{/if}
						<Tabs.Content value="citation">
							{#if open && section === 'citation'}
								<div class="grid grid-cols-1 gap-3">
									<div>
										<h2>{$t('Export bibliography')}</h2>
										<p class="text-surface-600-400">
											{$t('Uses the defaults saved in your Account export preferences.')}
										</p>
									</div>
									<label
										>{$t('Format')}<select class="select" bind:value={format}>
											{#each bibliographyFormats as choice (choice.value)}
												<option value={choice.value}>{$t(choice.label)}</option>
											{/each}
										</select></label
									>
									<div class="flex flex-wrap gap-2">
										<Button variant="filled" disabled={busy} onclick={downloadBibliography}
											>{$t('Download file')}</Button
										>

										<Button disabled={busy} onclick={copyBibliography}
											>{$t('Copy to clipboard')}</Button
										>
										<Button onclick={() => goto(resolve('account'))}>{$t('Export settings')}</Button
										>
									</div>
								</div>
							{/if}
						</Tabs.Content>
						<Tabs.Content value="copy">
							{#if open && section === 'copy'}
								<div class="grid max-w-xl grid-cols-1 gap-3">
									<h2>{$t('Copy to another Workspace')}</h2>
									<p class="text-surface-600-400">
										{$t(
											'A copy creates a new canonical Item. Only Workspaces where you can create Items are offered.'
										)}
									</p>
									<SearchSelect
										label={$t('Target Workspace')}
										bind:value={targetWorkspaceId}
										emptyLabel={$t('Choose a Workspace')}
										disabled={busy}
										options={copyDestinations.map(
											(target: ItemOverviewView['copy_targets'][number]) => ({
												value: target.id,
												label: target.name
											})
										)}
									/>
									<div class="flex flex-wrap gap-2">
										<Button
											variant="filled"
											disabled={busy || !targetWorkspaceId}
											onclick={copyItem}>{$t('Create copy')}</Button
										>{#if copiedItemUrl}<Button as="a" href={copiedItemUrl}
												>{$t('Open copy')}</Button
											>{/if}
									</div>
								</div>
							{/if}
						</Tabs.Content>
						<Tabs.Content value="documents">
							{#if open && section === 'documents'}
								<div class="grid grid-cols-1 gap-3">
									<div>
										<h2>{$t('Download documents')}</h2>
										<p class="text-surface-600-400">
											{$t('Choose PDF revisions to package with saved download preferences.')}
										</p>
									</div>
									{#each revisions as revision (revision.id)}<label
											class="flex min-w-0 items-start gap-3 rounded-lg border border-surface-300-700 p-3"
											><input
												type="checkbox"
												class="mt-1 shrink-0"
												checked={selectedRevisions.has(revision.id)}
												disabled={busy || files.isFetching || files.isError}
												onchange={() =>
													selectedRevisions.has(revision.id)
														? selectedRevisions.delete(revision.id)
														: selectedRevisions.add(revision.id)}
											/><span class="min-w-0 flex-1"
												><strong class="block wrap-anywhere">{revision.original_name}</strong><small
													class="block text-surface-600-400"
													>{$t(domainLabel(revision.processing_state ?? 'pending'))}</small
												></span
											></label
										>{/each}
									{#if files.isError}<QueryError
											message={apiErrorMessage(files.error, $t('Unable to load documents.'))}
											busy={files.isFetching}
											onRetry={() => void files.refetch()}
										/>{:else if files.isPending}<LoadingState label={$t('Loading documents…')} />
									{:else if revisions.length === 0}<p>{$t('No PDF revisions available.')}</p>{/if}
									<p class="text-sm text-surface-600-400">
										{$t('Annotations: {state}', {
											state: preferences.document.includeAnnotations
												? $t('included')
												: $t('excluded')
										})}
										· {$t('Supplements: {state}', {
											state: preferences.document.includeSupplements
												? $t('included')
												: $t('excluded')
										})}
									</p>
									<div class="flex flex-wrap gap-2">
										<Button
											variant="filled"
											disabled={busy ||
												files.isPending ||
												files.isError ||
												selectedRevisions.size === 0}
											onclick={downloadDocuments}>{$t('Download bundle')}</Button
										>
										<Button onclick={() => goto(resolve('account'))}>{$t('Export settings')}</Button
										>
									</div>
								</div>
							{/if}
						</Tabs.Content>
						<Tabs.Content value="sources">
							{#if open && section === 'sources'}
								<div class="grid grid-cols-1 gap-3">
									<div>
										<h2>{$t('Metadata sources')}</h2>
										<p class="text-surface-600-400">
											{$t('Refresh this record from an upstream identifier.')}
										</p>
									</div>
									{#if sources.isPending}
										<p>{$t('Loading…')}</p>
									{:else if sources.isError}
										<Notice variant="error"
											>{apiErrorMessage(
												sources.error,
												$t('Could not load metadata sources.')
											)}</Notice
										>
										<Button onclick={() => sources.refetch()}>{$t('Retry')}</Button>
									{:else}
										{#if doiSource}<div
												class="grid grid-cols-1 gap-3 rounded-lg border border-surface-300-700 p-3 sm:grid-cols-[1fr_auto] sm:items-center"
											>
												<div>
													<strong>DOI</strong><span class="block text-sm text-surface-600-400"
														>{doiSource.value}</span
													>
												</div>
												<div class="flex flex-wrap items-center gap-2">
													<select
														class="select h-8 w-auto min-w-36"
														bind:value={doiProvider}
														aria-label={$t('Provider')}
													>
														<option value="auto">{$t('Auto detect')}</option>
														{#each doiProviders as choice (choice.id)}
															<option value={choice.id}>{choice.name}</option>
														{/each}
													</select>
													<Button
														disabled={busy}
														onclick={() => synchronize(doiProvider, doiSource!.value)}
														>{$t('Autoupdate')}</Button
													>
												</div>
											</div>{:else if overview.latest_revision_id}<Button
												disabled={busy}
												onclick={rescanDoi}>{$t('Rescan PDF for DOI')}</Button
											>{/if}
										{#each externalIdentifiers as identifier (JSON.stringify( [identifier.namespace, identifier.value] ))}<div
												class="grid grid-cols-1 gap-3 rounded-lg border border-surface-300-700 p-3 sm:grid-cols-[1fr_auto] sm:items-center"
											>
												<div>
													<strong>{identifier.namespace.toUpperCase()}</strong><span
														class="block text-sm text-surface-600-400">{identifier.value}</span
													>
												</div>
												{#if identifier.providers[0]?.id}
													<Button
														disabled={busy}
														onclick={() =>
															synchronize(identifier.providers[0].id, identifier.value)}
														>{$t('Autoupdate')}</Button
													>
												{/if}
											</div>{/each}
									{/if}
									<div class="border-t border-surface-300-700 pt-4">
										<Button disabled={busy} onclick={regenerateCitationKey}
											>{$t('Regenerate citation key')}</Button
										>
									</div>
								</div>
							{/if}
						</Tabs.Content>
						<Tabs.Content value="danger">
							{#if open && section === 'danger'}
								<div class="grid grid-cols-1 gap-3">
									<div>
										<h2 class="text-error-700-300">{$t('Delete Item')}</h2>
										<p class="text-surface-600-400">
											{$t(
												'Associated files, annotations, and assignments of this Item to Projects will also be removed.'
											)}
										</p>
									</div>
									{#if deleteArmed}
										<p class="text-sm text-error-700-300" role="alert">
											{$t('This cannot be undone. Delete this Item permanently?')}
										</p>
										<div class="flex flex-wrap gap-2">
											<Button disabled={busy} onclick={() => (deleteArmed = false)}
												>{$t('Cancel')}</Button
											>

											<Button variant="danger-filled" disabled={busy} onclick={confirmDeleteItem}
												>{$t('Delete Item permanently')}</Button
											>
										</div>
									{:else}
										<Button variant="danger" disabled={busy} onclick={deleteItem}
											>{$t('Delete Item permanently')}</Button
										>
									{/if}
								</div>
							{/if}
						</Tabs.Content>
					</div>
				</Tabs>
			</Dialog.Content>
		</Dialog.Positioner>
	</Portal>
</Dialog>
