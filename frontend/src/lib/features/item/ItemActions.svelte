<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { Dialog, Portal } from '@skeletonlabs/skeleton-svelte';
	import { createQuery } from '@tanstack/svelte-query';
	import { onMount } from 'svelte';
	import { SvelteSet } from 'svelte/reactivity';
	import { apiDownloadGet, apiRequest, apiText, type WorkspaceView } from '$lib/api/client';
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
	import { t } from '$lib/i18n';

	type ActionSection = 'documents' | 'citation' | 'sources' | 'danger';

	let { itemId, workspace, userId, onchanged } = $props<{
		itemId: string;
		workspace: WorkspaceView;
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
	const files = createQuery(() => itemFilesQuery(itemId, open && section === 'documents'));
	const revisions = $derived(files.data?.files.filter((file) => file.kind === 'revision') ?? []);

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

	async function action(operation: () => Promise<unknown>, success: string) {
		busy = true;
		error = '';
		notice = '';
		try {
			await operation();
			notice = success;
		} catch (reason) {
			error = apiErrorMessage(reason, $t('Item action failed'));
		} finally {
			busy = false;
		}
	}

	function downloadBibliography() {
		void action(
			() =>
				apiDownloadGet('/items/{item_id}/bibliography', {
					params: { path: { item_id: itemId }, query: bibliographyParameters() }
				}),
			$t('Bibliography downloaded')
		);
	}

	function copyBibliography() {
		void action(async () => {
			const content = await apiText('/items/{item_id}/bibliography/content', {
				params: { path: { item_id: itemId }, query: bibliographyParameters() }
			});
			await navigator.clipboard.writeText(content);
		}, $t('Copied to clipboard'));
	}

	function downloadDocuments() {
		void action(
			() =>
				apiDownloadGet('/items/{item_id}/archive', {
					params: {
						path: { item_id: itemId },
						query: {
							revisions: [...selectedRevisions].join(','),
							include_annotations: preferences.document.includeAnnotations,
							include_supplements: preferences.document.includeSupplements,
							timezone: Intl.DateTimeFormat().resolvedOptions().timeZone
						}
					}
				}),
			$t('Document bundle downloaded')
		);
	}

	function synchronize(provider: string, uid: string) {
		void action(async () => {
			await apiRequest('POST', '/items/{item_id}/metadata/sync', {
				params: { path: { item_id: itemId } },
				body: { expected_version: workspace.item.version, provider, uid }
			});
			await onchanged();
		}, $t('Metadata synchronized'));
	}

	function regenerateCitationKey() {
		void action(async () => {
			await apiRequest('POST', '/items/{item_id}/citation-key/regenerate', {
				params: { path: { item_id: itemId } }
			});
			await onchanged();
		}, $t('Citation key updated'));
	}

	function rescanDoi() {
		void action(async () => {
			await apiRequest('POST', '/items/{item_id}/doi/rescan', {
				params: { path: { item_id: itemId } }
			});
			await onchanged();
		}, $t('PDF scanned for a DOI'));
	}

	function deleteItem() {
		deleteArmed = true;
	}

	function confirmDeleteItem() {
		deleteArmed = false;
		void action(async () => {
			await apiRequest('DELETE', '/items/{item_id}', {
				params: { path: { item_id: itemId } },
				body: { confirmation: 'delete' }
			});
			await goto(resolve('/library'));
		}, $t('Item deleted'));
	}
</script>

<div class="flex flex-wrap gap-2">
	{#if workspace.latest_revision}<Button
			as="a"
			variant="filled"
			class="inline-flex items-center gap-2"
			href={resolve('/(app)/item/[itemId]/pdf/[revisionId]', {
				itemId,
				revisionId: workspace.latest_revision.id
			})}>{$t('Read PDF')}</Button
		><Button class="inline-flex items-center gap-2" onclick={() => show('documents')}
			><Icon name="download" /> {$t('Download')}</Button
		>{/if}
	<Button onclick={() => show('citation')}>{$t('Export')}</Button>
	{#if workspace.permissions.edit}<Button onclick={() => show('sources')}
			>{$t('Record tools')}</Button
		>{/if}
	{#if workspace.permissions.delete}<Button variant="danger" onclick={() => show('danger')}
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
					{#if workspace.latest_revision}<button
							class="border-0 border-b-2 bg-transparent px-3 py-2 text-sm font-semibold data-[active=true]:border-primary-700-300 data-[active=true]:text-primary-700-300"
							data-active={section === 'documents'}
							onclick={() => (section = 'documents')}>{$t('Documents')}</button
						>{/if}
					{#if workspace.permissions.edit}<button
							class="border-0 border-b-2 bg-transparent px-3 py-2 text-sm font-semibold data-[active=true]:border-primary-700-300 data-[active=true]:text-primary-700-300"
							data-active={section === 'sources'}
							onclick={() => (section = 'sources')}>{$t('Metadata sources')}</button
						>{/if}
					{#if workspace.permissions.delete}<button
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
								{$t('Annotations')}: {preferences.document.includeAnnotations
									? $t('included')
									: $t('excluded')}
								· {$t('Supplements')}: {preferences.document.includeSupplements
									? $t('included')
									: $t('excluded')}
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
							{#if workspace.item.doi}<div
									class="grid grid-cols-1 gap-3 rounded-lg border border-surface-300-700 p-3 sm:grid-cols-[1fr_auto] sm:items-center"
								>
									<div>
										<strong>DOI</strong><span class="block text-sm text-surface-600-400"
											>{workspace.item.doi}</span
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
											onclick={() => synchronize(doiProvider, workspace.item.doi!)}
											>{$t('Autoupdate')}</Button
										>
									</div>
								</div>{:else if workspace.latest_revision}<Button
									disabled={busy}
									onclick={rescanDoi}>{$t('Rescan PDF for DOI')}</Button
								>{/if}
							{#each workspace.identifiers.filter((identifier: WorkspaceView['identifiers'][number]) => identifier.provider !== 'doi') as identifier (`${identifier.provider}:${identifier.value}`)}<div
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
