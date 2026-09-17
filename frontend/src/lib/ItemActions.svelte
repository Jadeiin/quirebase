<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { Dialog, Portal } from '@skeletonlabs/skeleton-svelte';
	import { createQuery } from '@tanstack/svelte-query';
	import { onMount } from 'svelte';
	import { SvelteSet, SvelteURLSearchParams } from 'svelte/reactivity';
	import { apiDownloadGet, apiRequest, apiText, type WorkspaceView } from '$lib/api/client';
	import Icon from '$lib/design/Icon.svelte';
	import { domainLabel } from '$lib/domain-labels';
	import {
		defaultExportPreferences,
		readExportPreferences,
		type ExportPreferences
	} from '$lib/export-preferences';
	import { t } from '$lib/i18n';

	type FileRow = {
		id: string;
		original_name: string;
	} & (
		| { kind: 'revision'; processing_state: 'pending' | 'ready' }
		| { kind: 'attachment'; processing_state: null }
	);
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
	const files = createQuery(() => ({
		queryKey: ['item-actions-files', itemId],
		enabled: open && section === 'documents',
		queryFn: () => apiRequest<{ files: FileRow[] }>(`/items/${itemId}/documents`)
	}));
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
		error = '';
		notice = '';
		open = true;
	}

	function bibliographyParameters() {
		const citation = preferences.citation;
		const parameters = new SvelteURLSearchParams({
			file_format: format,
			style: citation.style,
			include_abstract: String(citation.includeAbstract),
			preserve_case: String(citation.preserveCase),
			include_identifiers: String(citation.includeIdentifiers),
			include_custom_fields: String(citation.includeCustomFields),
			encoding: citation.encoding,
			journal_mode: citation.journalMode,
			doi_policy: citation.doiPolicy,
			url_policy: citation.urlPolicy,
			excluded_fields: citation.excludedFields,
			sort_by: citation.sortBy,
			citation_key_formula: citation.citationKeyFormula,
			citation_key_force_ascii: String(citation.citationKeyForceAscii)
		});
		return parameters.toString();
	}

	async function action(operation: () => Promise<unknown>, success: string) {
		busy = true;
		error = '';
		notice = '';
		try {
			await operation();
			notice = success;
		} catch (reason) {
			error = reason instanceof Error ? reason.message : $t('Item action failed');
		} finally {
			busy = false;
		}
	}

	function downloadBibliography() {
		void action(
			() => apiDownloadGet(`/items/${itemId}/bibliography?${bibliographyParameters()}`),
			$t('Bibliography downloaded')
		);
	}

	function copyBibliography() {
		void action(async () => {
			const content = await apiText(
				`/items/${itemId}/bibliography/content?${bibliographyParameters()}`
			);
			await navigator.clipboard.writeText(content);
		}, $t('Copied to clipboard'));
	}

	function downloadDocuments() {
		const parameters = new SvelteURLSearchParams({
			revisions: [...selectedRevisions].join(','),
			include_annotations: String(preferences.document.includeAnnotations),
			include_supplements: String(preferences.document.includeSupplements),
			timezone: Intl.DateTimeFormat().resolvedOptions().timeZone
		});
		void action(
			() => apiDownloadGet(`/items/${itemId}/archive?${parameters}`),
			$t('Document bundle downloaded')
		);
	}

	function synchronize(provider: string, uid: string) {
		void action(async () => {
			await apiRequest(`/items/${itemId}/metadata/sync`, {
				method: 'POST',
				body: { expected_version: workspace.item.version, provider, uid }
			});
			await onchanged();
		}, $t('Metadata synchronized'));
	}

	function regenerateCitationKey() {
		void action(async () => {
			await apiRequest(`/items/${itemId}/citation-key/regenerate`, { method: 'POST' });
			await onchanged();
		}, $t('Citation key updated'));
	}

	function rescanDoi() {
		void action(async () => {
			await apiRequest(`/items/${itemId}/doi/rescan`, { method: 'POST' });
			await onchanged();
		}, $t('PDF scanned for a DOI'));
	}

	function deleteItem() {
		if (!window.confirm($t('Delete this Item permanently?'))) return;
		void action(async () => {
			await apiRequest(`/items/${itemId}`, {
				method: 'DELETE',
				body: { confirmation: 'delete' }
			});
			await goto(resolve('/library'));
		}, $t('Item deleted'));
	}
</script>

<div class="flex flex-wrap gap-2">
	{#if workspace.latest_revision}<a
			class="btn inline-flex items-center gap-2 preset-filled-primary-700-300 font-semibold"
			href={resolve('/(app)/item/[itemId]/pdf/[revisionId]', {
				itemId,
				revisionId: workspace.latest_revision.id
			})}>{$t('Read PDF')}</a
		><button
			class="btn inline-flex items-center gap-2 preset-tonal-surface font-semibold"
			onclick={() => show('documents')}><Icon name="download" /> {$t('Download')}</button
		>{/if}
	<button class="btn preset-tonal-surface font-semibold" onclick={() => show('citation')}
		>{$t('Export')}</button
	>
	{#if workspace.permissions.edit}<button
			class="btn preset-tonal-surface font-semibold"
			onclick={() => show('sources')}>{$t('Record tools')}</button
		>{/if}
	{#if workspace.permissions.delete}<button
			class="btn preset-tonal-error font-semibold"
			onclick={() => show('danger')}>{$t('More')}</button
		>{/if}
</div>

<Dialog {open} onOpenChange={(details) => (open = details.open)}>
	<Portal>
		<Dialog.Backdrop class="fixed inset-0 z-70 bg-surface-950/45 backdrop-blur-[2px]" />
		<Dialog.Positioner class="fixed inset-0 z-71 grid place-items-center p-4">
			<Dialog.Content
				class="grid max-h-[min(46rem,calc(100dvh-2rem))] w-full max-w-3xl grid-rows-[auto_auto_minmax(0,1fr)] overflow-hidden rounded-container border border-surface-300 bg-surface-50 shadow-2xl"
			>
				<header class="flex items-center justify-between border-b border-surface-300 px-5 py-4">
					<Dialog.Title class="text-lg font-bold">{$t('Item actions')}</Dialog.Title>
					<Dialog.CloseTrigger class="btn-icon preset-tonal-surface" aria-label={$t('Close')}
						><Icon name="close" /></Dialog.CloseTrigger
					>
				</header>
				<nav
					class="flex gap-1 overflow-x-auto border-b border-surface-300 px-3 pt-2"
					aria-label={$t('Item actions')}
				>
					<button
						class="border-0 border-b-2 bg-transparent px-3 py-2 text-sm font-semibold data-[active=true]:border-primary-700 data-[active=true]:text-primary-700"
						data-active={section === 'citation'}
						onclick={() => (section = 'citation')}>{$t('Citation')}</button
					>
					{#if workspace.latest_revision}<button
							class="border-0 border-b-2 bg-transparent px-3 py-2 text-sm font-semibold data-[active=true]:border-primary-700 data-[active=true]:text-primary-700"
							data-active={section === 'documents'}
							onclick={() => (section = 'documents')}>{$t('Documents')}</button
						>{/if}
					{#if workspace.permissions.edit}<button
							class="border-0 border-b-2 bg-transparent px-3 py-2 text-sm font-semibold data-[active=true]:border-primary-700 data-[active=true]:text-primary-700"
							data-active={section === 'sources'}
							onclick={() => (section = 'sources')}>{$t('Metadata sources')}</button
						>{/if}
					{#if workspace.permissions.delete}<button
							class="border-0 border-b-2 bg-transparent px-3 py-2 text-sm font-semibold text-error-700 data-[active=true]:border-error-700"
							data-active={section === 'danger'}
							onclick={() => (section = 'danger')}>{$t('Danger zone')}</button
						>{/if}
				</nav>
				<div class="overflow-auto p-5">
					{#if error}<p class="text-error-700" role="alert">{error}</p>{/if}
					{#if notice}<p
							class="rounded-base border border-success-200 preset-tonal-success px-4 py-3 text-success-900"
							role="status"
						>
							{notice}
						</p>{/if}
					{#if section === 'citation'}
						<div class="stack">
							<div>
								<h2>{$t('Export bibliography')}</h2>
								<p class="text-surface-600">
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
							<div class="toolbar">
								<button
									class="btn preset-filled-primary-700-300 font-semibold"
									disabled={busy}
									onclick={downloadBibliography}>{$t('Download file')}</button
								><button
									class="btn preset-tonal-surface font-semibold"
									disabled={busy}
									onclick={copyBibliography}>{$t('Copy to clipboard')}</button
								><button
									class="btn preset-tonal-surface font-semibold"
									onclick={() => goto(resolve('/account'))}>{$t('Export settings')}</button
								>
							</div>
						</div>
					{:else if section === 'documents'}
						<div class="stack">
							<div>
								<h2>{$t('Download documents')}</h2>
								<p class="text-surface-600">
									{$t('Choose PDF revisions to package with saved download preferences.')}
								</p>
							</div>
							{#each revisions as revision (revision.id)}<label
									class="flex items-center gap-3 rounded-lg border border-surface-300 p-3"
									><input
										type="checkbox"
										checked={selectedRevisions.has(revision.id)}
										onchange={() =>
											selectedRevisions.has(revision.id)
												? selectedRevisions.delete(revision.id)
												: selectedRevisions.add(revision.id)}
									/><span
										><strong>{revision.original_name}</strong><small class="block text-surface-600"
											>{$t(domainLabel(revision.processing_state))}</small
										></span
									></label
								>{/each}
							<p class="text-sm text-surface-600">
								{$t('Annotations')}: {preferences.document.includeAnnotations
									? $t('included')
									: $t('excluded')}
								· {$t('Supplements')}: {preferences.document.includeSupplements
									? $t('included')
									: $t('excluded')}
							</p>
							<div class="toolbar">
								<button
									class="btn preset-filled-primary-700-300 font-semibold"
									disabled={busy || selectedRevisions.size === 0}
									onclick={downloadDocuments}>{$t('Download bundle')}</button
								><button
									class="btn preset-tonal-surface font-semibold"
									onclick={() => goto(resolve('/account'))}>{$t('Export settings')}</button
								>
							</div>
						</div>
					{:else if section === 'sources'}
						<div class="stack">
							<div>
								<h2>{$t('Metadata sources')}</h2>
								<p class="text-surface-600">
									{$t('Refresh this record from an upstream identifier.')}
								</p>
							</div>
							{#if workspace.item.doi}<div
									class="grid gap-3 rounded-lg border border-surface-300 p-3 sm:grid-cols-[1fr_auto] sm:items-center"
								>
									<div>
										<strong>DOI</strong><span class="block text-sm text-surface-600"
											>{workspace.item.doi}</span
										>
									</div>
									<div class="toolbar items-center">
										<select
											class="compact input border border-surface-300"
											bind:value={doiProvider}
											aria-label={$t('Provider')}
										>
											<option value="auto">{$t('Auto detect')}</option>
											<option value="crossref">Crossref</option>
											<option value="openalex">OpenAlex</option>
											<option value="datacite">DataCite</option>
										</select>
										<button
											class="btn preset-tonal-surface font-semibold"
											disabled={busy}
											onclick={() => synchronize(doiProvider, workspace.item.doi!)}
											>{$t('Autoupdate')}</button
										>
									</div>
								</div>{:else if workspace.latest_revision}<button
									class="btn preset-tonal-surface font-semibold"
									disabled={busy}
									onclick={rescanDoi}>{$t('Rescan PDF for DOI')}</button
								>{/if}
							{#each workspace.identifiers.filter((identifier: WorkspaceView['identifiers'][number]) => identifier.provider !== 'doi') as identifier (`${identifier.provider}:${identifier.value}`)}<div
									class="grid gap-3 rounded-lg border border-surface-300 p-3 sm:grid-cols-[1fr_auto] sm:items-center"
								>
									<div>
										<strong>{identifier.provider.toUpperCase()}</strong><span
											class="block text-sm text-surface-600">{identifier.value}</span
										>
									</div>
									<button
										class="btn preset-tonal-surface font-semibold"
										disabled={busy}
										onclick={() => synchronize(identifier.provider, identifier.value)}
										>{$t('Autoupdate')}</button
									>
								</div>{/each}
							<div class="border-t border-surface-300 pt-4">
								<button
									class="btn preset-tonal-surface font-semibold"
									disabled={busy}
									onclick={regenerateCitationKey}>{$t('Regenerate citation key')}</button
								>
							</div>
						</div>
					{:else}
						<div class="stack">
							<div>
								<h2 class="text-error-700">{$t('Delete Item')}</h2>
								<p class="text-surface-600">
									{$t(
										'Associated files, annotations, and Project memberships will also be removed.'
									)}
								</p>
							</div>
							<button
								class="btn preset-tonal-error font-semibold"
								disabled={busy}
								onclick={deleteItem}>{$t('Delete Item permanently')}</button
							>
						</div>
					{/if}
				</div>
			</Dialog.Content>
		</Dialog.Positioner>
	</Portal>
</Dialog>
