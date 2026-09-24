<script lang="ts">
	import { resolve } from '$app/paths';
	import { goto } from '$app/navigation';
	import { Dialog, Portal } from '@skeletonlabs/skeleton-svelte';
	import { createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { onMount } from 'svelte';
	import { SvelteSet } from 'svelte/reactivity';
	import { isDownloadCancelled, type ItemOverviewView } from '$lib/api/client';
	import { apiErrorMessage } from '$lib/api/errors';
	import Button from '$lib/design/Button.svelte';
	import DialogCloseButton from '$lib/design/DialogCloseButton.svelte';
	import Icon from '$lib/design/Icon.svelte';
	import Notice from '$lib/design/Notice.svelte';
	import { domainLabel } from '$lib/domain-labels';
	import {
		defaultExportPreferences,
		readExportPreferences,
		type ExportPreferences
	} from '$lib/export-preferences';
	import { itemFilesQuery } from '$lib/features/item/queries';
	import { invalidateLibrary } from '$lib/query/invalidation';
	import { t } from '$lib/i18n';
	import { getWorkspaceContext } from '$lib/workspaces/context.svelte';
	import { workspaceHref } from '$lib/workspaces/href';
	import { workspaceListQuery } from '$lib/workspaces/queries';
	import { workspaceKeys } from '$lib/workspaces/keys';

	type ActionSection = 'documents' | 'citation' | 'sources' | 'danger' | 'copy';

	let { itemId, overview, userId, onchanged } = $props<{
		itemId: string;
		overview: ItemOverviewView;
		userId: string;
		onchanged: () => Promise<unknown>;
	}>();
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
	const workspaces = createQuery(() => workspaceListQuery());
	let targetWorkspaceId = $state('');
	let copiedItemUrl = $state('');
	const files = createQuery(() =>
		itemFilesQuery(workspaceId, itemId, open && section === 'documents')
	);
	const revisions = $derived(files.data?.files.filter((file) => file.kind === 'revision') ?? []);
	const copyDestinations = $derived(
		(workspaces.data ?? []).filter(
			(candidate) =>
				candidate.id !== workspaceId && candidate.effective_capabilities.includes('items.create')
		)
	);
	const externalIdentifiers = $derived(
		overview.identifiers.filter(
			(identifier: ItemOverviewView['identifiers'][number]) => identifier.provider !== 'doi'
		)
	);

	onMount(() => {
		preferences = readExportPreferences(userId);
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
		const citation = preferences.citation;
		return {
			file_format: format,
			style: citation.style,
			include_abstract: citation.includeAbstract,
			preserve_case: citation.preserveCase,
			include_identifiers: citation.includeIdentifiers,
			include_custom_fields: citation.includeCustomFields,
			encoding: citation.encoding,
			journal_mode: citation.journalMode,
			doi_policy: citation.doiPolicy,
			url_policy: citation.urlPolicy,
			excluded_fields: citation.excludedFields,
			sort_by: citation.sortBy,
			citation_key_formula: citation.citationKeyFormula,
			citation_key_force_ascii: citation.citationKeyForceAscii
		};
	}

	function bibliographyFilename() {
		if (format === 'csl') return 'quirebase-citations.txt';
		const extension = format === 'ris' ? 'ris' : format === 'endnote' ? 'enw' : 'bib';
		return `quirebase-export.${extension}`;
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
		busy = true;
		error = '';
		notice = '';
		try {
			await operation();
			notice = success;
		} catch (reason) {
			if (isDownloadCancelled(reason)) return;
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
					{ suggestedName: bibliographyFilename() }
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
		void action(async () => {
			await workspaceContext.api.request(
				'POST',
				'/workspaces/{workspace_id}/items/{item_id}/metadata/sync',
				{
					params: { path: { item_id: itemId } },
					body: { expected_version: overview.item.version, provider, uid }
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
		void action(async () => {
			await workspaceContext.api.request('DELETE', '/workspaces/{workspace_id}/items/{item_id}', {
				params: { path: { item_id: itemId } },
				body: { confirmation: 'delete' }
			});
			await invalidateLibrary(queryClient, workspaceId);
			await goto(resolve(workspaceHref(workspaceId, 'library')));
		}, $t('Item deleted'));
	}

	function copyItem() {
		if (!targetWorkspaceId) return;
		void action(async () => {
			const copied = await workspaceContext.api.request(
				'POST',
				'/workspaces/{workspace_id}/items/{item_id}/copy',
				{
					params: { path: { item_id: itemId } },
					body: { target_workspace_id: targetWorkspaceId }
				}
			);
			await queryClient.invalidateQueries({
				queryKey: workspaceKeys.items(copied.target_workspace_id)
			});
			copiedItemUrl = resolve(
				workspaceHref(copied.target_workspace_id, `item/${copied.target_item_id}`)
			);
		}, $t('Item copied to Workspace'));
	}
</script>

<div class="flex flex-wrap gap-2">
	{#if overview.latest_revision}<Button
			as="a"
			variant="filled"
			class="inline-flex items-center gap-2"
			href={resolve(
				workspaceHref(workspaceId, `item/${itemId}/pdf/${overview.latest_revision.id}`)
			)}>{$t('Read PDF')}</Button
		><Button class="inline-flex items-center gap-2" onclick={() => show('documents')}
			><Icon name="download" /> {$t('Download')}</Button
		>{/if}
	<Button onclick={() => show('citation')}>{$t('Export')}</Button>
	{#if overview.allowed_actions.edit && workspaceContext.can('items.edit')}<Button
			onclick={() => show('sources')}>{$t('Record tools')}</Button
		>{/if}
	{#if copyDestinations.length}<Button variant="tonal" onclick={() => show('copy')}
			>{$t('Copy to Workspace')}</Button
		>{/if}
	{#if overview.allowed_actions.delete}<Button variant="danger" onclick={() => show('danger')}
			>{$t('More')}</Button
		>{/if}
</div>

<Dialog {open} onOpenChange={(details) => (open = details.open)}>
	<Portal>
		<Dialog.Backdrop class="fixed inset-0 z-70 bg-surface-950/45 backdrop-blur-[2px]" />
		<Dialog.Positioner class="fixed inset-0 z-71 grid grid-cols-1 place-items-center p-4">
			<Dialog.Content
				class="grid max-h-[min(46rem,calc(100dvh-2rem))] w-full max-w-3xl grid-cols-1 grid-rows-[auto_auto_minmax(0,1fr)] overflow-hidden rounded-container border border-surface-300-700 bg-surface-50-950 shadow-2xl"
			>
				<header class="flex items-center justify-between border-b border-surface-300-700 px-5 py-4">
					<Dialog.Title class="text-lg font-bold">{$t('Item actions')}</Dialog.Title>
					<DialogCloseButton />
				</header>
				<nav
					class="flex gap-1 overflow-x-auto border-b border-surface-300-700 px-3 pt-2"
					aria-label={$t('Item actions')}
				>
					<button
						class="border-0 border-b-2 bg-transparent px-3 py-2 text-sm font-semibold data-[active=true]:border-primary-700-300 data-[active=true]:text-primary-700-300"
						data-active={section === 'citation'}
						onclick={() => (section = 'citation')}>{$t('Citation')}</button
					>
					{#if copyDestinations.length}<button
							class="border-0 border-b-2 bg-transparent px-3 py-2 text-sm font-semibold data-[active=true]:border-primary-700-300 data-[active=true]:text-primary-700-300"
							data-active={section === 'copy'}
							onclick={() => (section = 'copy')}>{$t('Copy')}</button
						>{/if}
					{#if overview.latest_revision}<button
							class="border-0 border-b-2 bg-transparent px-3 py-2 text-sm font-semibold data-[active=true]:border-primary-700-300 data-[active=true]:text-primary-700-300"
							data-active={section === 'documents'}
							onclick={() => (section = 'documents')}>{$t('Documents')}</button
						>{/if}
					{#if overview.allowed_actions.edit && workspaceContext.can('items.edit')}<button
							class="border-0 border-b-2 bg-transparent px-3 py-2 text-sm font-semibold data-[active=true]:border-primary-700-300 data-[active=true]:text-primary-700-300"
							data-active={section === 'sources'}
							onclick={() => (section = 'sources')}>{$t('Metadata sources')}</button
						>{/if}
					{#if overview.allowed_actions.delete}<button
							class="border-0 border-b-2 bg-transparent px-3 py-2 text-sm font-semibold text-error-700-300 data-[active=true]:border-error-700-300"
							data-active={section === 'danger'}
							onclick={() => (section = 'danger')}>{$t('Danger zone')}</button
						>{/if}
				</nav>
				<div class="overflow-auto p-5">
					{#if error}<Notice variant="error">{error}</Notice>{/if}
					{#if notice}<Notice variant="success">{notice}</Notice>{/if}
					{#if section === 'citation'}
						<div class="grid grid-cols-1 gap-3">
							<div>
								<h2>{$t('Export bibliography')}</h2>
								<p class="text-surface-600-400">
									{$t('Uses the defaults saved in your Account export preferences.')}
								</p>
							</div>
							<label
								>{$t('Format')}<select class="select" bind:value={format}
									><option value="csl">CSL citation</option><option value="bibtex">BibTeX</option
									><option value="biblatex">BibLaTeX</option><option value="ris">RIS</option><option
										value="endnote">EndNote</option
									></select
								></label
							>
							<div class="flex flex-wrap gap-2">
								<Button variant="filled" disabled={busy} onclick={downloadBibliography}
									>{$t('Download file')}</Button
								><Button disabled={busy} onclick={copyBibliography}
									>{$t('Copy to clipboard')}</Button
								><Button onclick={() => goto(resolve('/account'))}>{$t('Export settings')}</Button>
							</div>
						</div>
					{:else if section === 'copy'}
						<div class="grid max-w-xl grid-cols-1 gap-3">
							<h2>{$t('Copy to another Workspace')}</h2>
							<p class="text-surface-600-400">
								{$t(
									'A copy creates a new canonical Item. Only Workspaces where you can create Items are offered.'
								)}
							</p>
							<label class="grid grid-cols-1 gap-1"
								>{$t('Target Workspace')}<select class="select" bind:value={targetWorkspaceId}
									><option value="">{$t('Choose a Workspace')}</option
									>{#each copyDestinations as target (target.id)}<option value={target.id}
											>{target.name}</option
										>{/each}</select
								></label
							>
							<div class="flex flex-wrap gap-2">
								<Button variant="filled" disabled={busy || !targetWorkspaceId} onclick={copyItem}
									>{$t('Create copy')}</Button
								>{#if copiedItemUrl}<Button as="a" href={copiedItemUrl}>{$t('Open copy')}</Button
									>{/if}
							</div>
						</div>
					{:else if section === 'documents'}
						<div class="grid grid-cols-1 gap-3">
							<div>
								<h2>{$t('Download documents')}</h2>
								<p class="text-surface-600-400">
									{$t('Choose PDF revisions to package with saved download preferences.')}
								</p>
							</div>
							{#each revisions as revision (revision.id)}<label
									class="flex items-center gap-3 rounded-lg border border-surface-300-700 p-3"
									><input
										type="checkbox"
										checked={selectedRevisions.has(revision.id)}
										onchange={() =>
											selectedRevisions.has(revision.id)
												? selectedRevisions.delete(revision.id)
												: selectedRevisions.add(revision.id)}
									/><span
										><strong>{revision.original_name}</strong><small
											class="block text-surface-600-400"
											>{$t(domainLabel(revision.processing_state ?? 'pending'))}</small
										></span
									></label
								>{/each}
							<p class="text-sm text-surface-600-400">
								{$t('Annotations: {state}', {
									state: preferences.document.includeAnnotations ? $t('included') : $t('excluded')
								})}
								· {$t('Supplements: {state}', {
									state: preferences.document.includeSupplements ? $t('included') : $t('excluded')
								})}
							</p>
							<div class="flex flex-wrap gap-2">
								<Button
									variant="filled"
									disabled={busy || selectedRevisions.size === 0}
									onclick={downloadDocuments}>{$t('Download bundle')}</Button
								>
								<Button onclick={() => goto(resolve('/account'))}>{$t('Export settings')}</Button>
							</div>
						</div>
					{:else if section === 'sources'}
						<div class="grid grid-cols-1 gap-3">
							<div>
								<h2>{$t('Metadata sources')}</h2>
								<p class="text-surface-600-400">
									{$t('Refresh this record from an upstream identifier.')}
								</p>
							</div>
							{#if overview.item.doi}<div
									class="grid grid-cols-1 gap-3 rounded-lg border border-surface-300-700 p-3 sm:grid-cols-[1fr_auto] sm:items-center"
								>
									<div>
										<strong>DOI</strong><span class="block text-sm text-surface-600-400"
											>{overview.item.doi}</span
										>
									</div>
									<div class="flex flex-wrap items-center gap-2">
										<select
											class="input w-auto min-w-36 border border-surface-300-700"
											bind:value={doiProvider}
											aria-label={$t('Provider')}
										>
											<option value="auto">{$t('Auto detect')}</option>
											<option value="crossref">Crossref</option>
											<option value="openalex">OpenAlex</option>
											<option value="datacite">DataCite</option>
										</select>
										<Button
											disabled={busy}
											onclick={() => synchronize(doiProvider, overview.item.doi!)}
											>{$t('Autoupdate')}</Button
										>
									</div>
								</div>{:else if overview.latest_revision}<Button disabled={busy} onclick={rescanDoi}
									>{$t('Rescan PDF for DOI')}</Button
								>{/if}
							{#each externalIdentifiers as identifier (`${identifier.provider}:${identifier.value}`)}<div
									class="grid grid-cols-1 gap-3 rounded-lg border border-surface-300-700 p-3 sm:grid-cols-[1fr_auto] sm:items-center"
								>
									<div>
										<strong>{identifier.provider.toUpperCase()}</strong><span
											class="block text-sm text-surface-600-400">{identifier.value}</span
										>
									</div>
									<Button
										disabled={busy}
										onclick={() => synchronize(identifier.provider, identifier.value)}
										>{$t('Autoupdate')}</Button
									>
								</div>{/each}
							<div class="border-t border-surface-300-700 pt-4">
								<Button disabled={busy} onclick={regenerateCitationKey}
									>{$t('Regenerate citation key')}</Button
								>
							</div>
						</div>
					{:else}
						<div class="grid grid-cols-1 gap-3">
							<div>
								<h2 class="text-error-700-300">{$t('Delete Item')}</h2>
								<p class="text-surface-600-400">
									{$t(
										'Associated files, annotations, and Project memberships will also be removed.'
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
				</div>
			</Dialog.Content>
		</Dialog.Positioner>
	</Portal>
</Dialog>
