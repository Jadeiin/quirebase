<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { useQueryClient } from '@tanstack/svelte-query';
	import { onDestroy, onMount } from 'svelte';
	import { SvelteMap } from 'svelte/reactivity';
	import { apiRequest } from '$lib/api/client';
	import type { components } from '$lib/api/schema';
	import Icon from '$lib/design/Icon.svelte';
	import RichText from '$lib/design/RichText.svelte';
	import ItemMetadataForm from '$lib/ItemMetadataForm.svelte';
	import { domainLabel } from '$lib/domain-labels';
	import { t } from '$lib/i18n';

	type ImportBatch = {
		id: string;
		status: string;
		workflow_id: string | null;
		records: Array<Record<string, unknown>>;
		errors: Array<Record<string, unknown>>;
	};

	let identifier = $state('');
	let provider = $state('auto');
	let batch = $state<ImportBatch | null>(null);
	let error = $state('');
	let busy = $state(false);
	let previewPage = $state(1);
	let manualOpen = $state(false);
	let pdfFiles = $state<File[]>([]);
	let pdfInput: HTMLInputElement;
	const pageSize = 20;
	let pollTimer: number | undefined;
	let pollGeneration = 0;
	const queryClient = useQueryClient();
	const emptyMetadata: components['schemas']['ItemMetadata-Input'] = {
		title: '',
		keywords: [],
		urls: [],
		authors: [],
		editors: [],
		identifiers: [],
		custom_fields: []
	};

	function stopPolling() {
		pollGeneration += 1;
		if (pollTimer !== undefined) window.clearTimeout(pollTimer);
		pollTimer = undefined;
	}

	function acceptBatch(next: ImportBatch) {
		stopPolling();
		batch = next;
		previewPage = 1;
		if (next.status === 'pending') schedulePoll(next.id, pollGeneration);
	}

	async function loadBatch(batchId: string) {
		busy = true;
		error = '';
		try {
			acceptBatch(await apiRequest<ImportBatch>(`/imports/${batchId}`));
		} catch (reason) {
			error = reason instanceof Error ? reason.message : $t('Unable to load Import preview');
		} finally {
			busy = false;
		}
	}

	function schedulePoll(batchId: string, generation: number, delay = 0) {
		pollTimer = window.setTimeout(async () => {
			if (generation !== pollGeneration || batch?.id !== batchId) return;
			try {
				const refreshed = await apiRequest<ImportBatch>(`/imports/${batchId}`);
				if (generation !== pollGeneration || batch?.id !== batchId) return;
				batch = refreshed;
				error = '';
				if (refreshed.status === 'pending') schedulePoll(batchId, generation, 500);
			} catch (reason) {
				error = reason instanceof Error ? reason.message : $t('Unable to refresh Import preview');
				if (generation === pollGeneration && batch?.id === batchId) {
					schedulePoll(batchId, generation, 1_000);
				}
			}
		}, delay);
	}

	async function importIdentifier() {
		busy = true;
		error = '';
		try {
			acceptBatch(
				await apiRequest<ImportBatch>('/imports/identifier', {
					method: 'POST',
					body: { identifier, provider }
				})
			);
		} catch (reason) {
			error = reason instanceof Error ? reason.message : $t('Import preview failed');
		} finally {
			busy = false;
		}
	}

	async function upload(event: Event, kind: 'bibliography' | 'pdfs') {
		const form = event.currentTarget as HTMLFormElement;
		busy = true;
		error = '';
		try {
			const body = new FormData(form);
			if (kind === 'pdfs') {
				body.delete('pdfs');
				for (const file of pdfFiles) body.append('pdfs', file);
			}
			acceptBatch(
				await apiRequest<ImportBatch>(`/imports/${kind}`, {
					method: 'POST',
					body
				})
			);
			if (kind === 'pdfs') {
				pdfFiles = [];
				pdfInput.value = '';
			}
		} catch (reason) {
			error = reason instanceof Error ? reason.message : $t('Upload failed');
		} finally {
			busy = false;
		}
	}

	function addPdfFiles(event: Event) {
		const input = event.currentTarget as HTMLInputElement;
		const files = new SvelteMap(
			pdfFiles.map((file) => [`${file.name}:${file.size}:${file.lastModified}`, file] as const)
		);
		for (const file of input.files ?? []) {
			files.set(`${file.name}:${file.size}:${file.lastModified}`, file);
		}
		pdfFiles = [...files.values()];
	}

	function removePdf(file: File) {
		pdfFiles = pdfFiles.filter((candidate) => candidate !== file);
		if (pdfFiles.length === 0) pdfInput.value = '';
	}

	async function retry() {
		if (!batch) return;
		busy = true;
		error = '';
		try {
			const result = await apiRequest<Pick<ImportBatch, 'id' | 'status' | 'workflow_id'>>(
				`/imports/${batch.id}/retry`,
				{ method: 'POST' }
			);
			acceptBatch({ ...batch, ...result, errors: [] });
		} catch (reason) {
			error = reason instanceof Error ? reason.message : $t('Unable to retry Import');
		} finally {
			busy = false;
		}
	}

	async function commit() {
		if (!batch || batch.status !== 'ready' || busy) return;
		busy = true;
		error = '';
		try {
			await apiRequest(`/imports/${batch.id}/commit`, { method: 'POST' });
			stopPolling();
			await queryClient.invalidateQueries({ queryKey: ['library'] });
			await goto(resolve('/library'));
		} catch (reason) {
			error = reason instanceof Error ? reason.message : $t('Unable to commit Import');
		} finally {
			busy = false;
		}
	}

	async function discard() {
		if (!batch || busy) return;
		busy = true;
		error = '';
		try {
			await apiRequest(`/imports/${batch.id}`, { method: 'DELETE' });
			stopPolling();
			batch = null;
		} catch (reason) {
			error = reason instanceof Error ? reason.message : $t('Unable to discard Import');
		} finally {
			busy = false;
		}
	}

	async function createItem(metadata: components['schemas']['ItemMetadata-Input']) {
		busy = true;
		error = '';
		try {
			const item = await apiRequest<{ id: string }>('/items', { method: 'POST', body: metadata });
			await queryClient.invalidateQueries({ queryKey: ['library'] });
			await goto(resolve('/(app)/item/[itemId]', { itemId: item.id }));
		} catch (reason) {
			error = reason instanceof Error ? reason.message : $t('Unable to create Item');
		} finally {
			busy = false;
		}
	}

	const previewRecords = $derived(
		batch?.records.slice((previewPage - 1) * pageSize, previewPage * pageSize) ?? []
	);
	const previewPageCount = $derived(
		batch ? Math.max(1, Math.ceil(batch.records.length / pageSize)) : 1
	);

	onMount(() => {
		const batchId = page.url.searchParams.get('batch');
		if (batchId) void loadBatch(batchId);
	});
	onDestroy(stopPolling);
</script>

<div class="mb-7 flex flex-wrap items-end justify-between gap-4">
	<div>
		<p class="mb-2 text-xs font-bold tracking-[0.12em] text-primary-700 uppercase">
			{$t('Add to Library')}
		</p>
		<h1 class="mb-2">{$t('Import')}</h1>
		<p class="mb-0 max-w-2xl text-surface-600">
			{$t('Bring records into Quirebase from an identifier, a bibliography, or published PDFs.')}
		</p>
	</div>
</div>
<ol
	class="mb-5 grid list-none gap-px overflow-hidden rounded-xl border border-surface-300 bg-surface-300 p-0 sm:grid-cols-3"
>
	{#each [{ number: '1', title: $t('Choose a source'), text: $t('Identifier, file, or PDFs') }, { number: '2', title: $t('Review the preview'), text: $t('Check records and diagnostics') }, { number: '3', title: $t('Commit to Library'), text: $t('Save only when you approve') }] as step (step.number)}
		<li class="flex items-center gap-3 bg-surface-50 px-4 py-3">
			<span
				class="grid size-7 shrink-0 place-items-center rounded-full bg-primary-50 text-xs font-bold text-primary-800"
				>{step.number}</span
			>
			<span class="min-w-0"
				><strong class="block text-sm">{step.title}</strong><small class="text-surface-600"
					>{step.text}</small
				></span
			>
		</li>
	{/each}
</ol>
{#if error}<p class="text-error-700" role="alert">{error}</p>{/if}
<div class="grid items-start gap-4 lg:grid-cols-3">
	<form
		class="stack h-full card border border-surface-300 bg-surface-50 p-5 shadow-sm"
		onsubmit={(event) => {
			event.preventDefault();
			importIdentifier();
		}}
	>
		<div class="flex items-start gap-3">
			<span
				class="grid size-10 shrink-0 place-items-center rounded-lg bg-primary-50 text-primary-800"
				><Icon name="search" size={20} /></span
			>
			<div>
				<h2 class="mb-1">{$t('Look up an identifier')}</h2>
				<p class="mb-0 text-sm text-surface-600">
					{$t('Fetch one record from DOI, PubMed, arXiv, and other scholarly providers.')}
				</p>
			</div>
		</div>
		<label
			>{$t('DOI, PMID, or arXiv ID')}<input
				class="input"
				bind:value={identifier}
				placeholder="DOI, PMID, arXiv ID…"
				required
			/></label
		>
		<label
			>{$t('Data source')}<select class="select" bind:value={provider}>
				<option value="auto">{$t('Auto detect')}</option><option value="crossref">Crossref</option>
				<option value="pubmed">PubMed</option><option value="arxiv">arXiv</option>
				<option value="openalex">OpenAlex</option><option value="openlibrary">Open Library</option>
				<option value="pmc">PMC</option><option value="nasa">NASA ADS</option><option value="ieee"
					>IEEE Xplore</option
				>
			</select></label
		>
		<button class="btn preset-filled-primary-700-300 font-semibold" disabled={busy}
			>{$t('Preview metadata')}</button
		>
	</form>
	<form
		class="stack h-full card border border-surface-300 bg-surface-50 p-5 shadow-sm"
		onsubmit={(event) => {
			event.preventDefault();
			upload(event, 'bibliography');
		}}
	>
		<div class="flex items-start gap-3">
			<span
				class="grid size-10 shrink-0 place-items-center rounded-lg bg-primary-50 text-primary-800"
				><Icon name="library" size={20} /></span
			>
			<div>
				<h2 class="mb-1">{$t('Upload a bibliography')}</h2>
				<p class="mb-0 text-sm text-surface-600">
					{$t('Stage many records from a reference manager export.')}
				</p>
			</div>
		</div>
		<label
			>{$t('Bibliography file')}<input
				class="input"
				type="file"
				name="bibliography"
				required
			/></label
		>
		<label
			>{$t('File format')}<select class="select" name="file_format">
				<option value="bibtex">BibTeX</option><option value="biblatex">BibLaTeX</option>
				<option value="ris">RIS</option><option value="endnote">EndNote</option>
			</select></label
		>
		<button class="btn preset-filled-primary-700-300 font-semibold" disabled={busy}
			>{$t('Preview bibliography')}</button
		>
	</form>
	<form
		class="stack h-full card border border-surface-300 bg-surface-50 p-5 shadow-sm"
		onsubmit={(event) => {
			event.preventDefault();
			upload(event, 'pdfs');
		}}
	>
		<div class="flex items-start gap-3">
			<span
				class="grid size-10 shrink-0 place-items-center rounded-lg bg-primary-50 text-primary-800"
				><Icon name="import" size={20} /></span
			>
			<div>
				<h2 class="mb-1">{$t('Import published PDFs')}</h2>
				<p class="mb-0 text-sm text-surface-600">
					{$t('Extract metadata and keep the papers together in one Import Batch.')}
				</p>
			</div>
		</div>
		<label
			>{$t('PDF files')}<input
				class="input"
				type="file"
				name="pdfs"
				accept="application/pdf,.pdf"
				multiple
				required={pdfFiles.length === 0}
				bind:this={pdfInput}
				onchange={addPdfFiles}
			/></label
		>
		<p class="text-sm text-surface-600">
			{$t('Choose PDFs more than once to add them to the same batch.')}
		</p>
		{#if pdfFiles.length}<ul class="m-0 grid list-none gap-2 p-0" aria-live="polite">
				{#each pdfFiles as file (`${file.name}:${file.size}:${file.lastModified}`)}<li
						class="flex items-center justify-between gap-3 rounded-lg border border-surface-300 px-3 py-2 text-sm"
					>
						<span class="truncate">{file.name}</span><button
							type="button"
							class="btn preset-tonal-surface font-semibold"
							onclick={() => removePdf(file)}>{$t('Remove')}</button
						>
					</li>{/each}
			</ul>{/if}
		<button
			class="btn preset-filled-primary-700-300 font-semibold"
			disabled={busy || pdfFiles.length === 0}>{$t('Stage PDFs')}</button
		>
	</form>
</div>
<section
	class="bg-surface/60 mt-4 flex flex-wrap items-center justify-between gap-4 rounded-xl border border-dashed border-surface-400 px-5 py-4"
>
	<div>
		<h2 class="mb-1">{$t('Create an Item manually')}</h2>
		<p class="mb-0 text-sm text-surface-600">
			{$t('Use the metadata editor when no import source is available.')}
		</p>
	</div>
	<button class="btn preset-tonal-surface font-semibold" onclick={() => (manualOpen = !manualOpen)}
		>{manualOpen ? $t('Close editor') : $t('Open metadata editor')}</button
	>
</section>
{#if manualOpen}
	<section class="list-panel stack card border border-surface-300 bg-surface-50 p-5 shadow-sm">
		<div>
			<p class="eyebrow">{$t('Manual creation')}</p>
			<h2>{$t('New Item metadata')}</h2>
		</div>
		<ItemMetadataForm
			metadata={emptyMetadata}
			{busy}
			submitLabel={$t('Create Item')}
			onsubmit={createItem}
		/>
	</section>
{/if}
{#if batch}
	<section class="mt-6 card border border-surface-300 bg-surface-50 p-5 shadow-sm">
		<div class="workspace-header">
			<div>
				<h2>{$t('Import preview')}</h2>
				<p class="text-surface-600">
					{batch.records.length}
					{$t('records')} · {batch.errors.length}
					{$t('diagnostics')} · {$t(domainLabel(batch.status))}
				</p>
			</div>
			<div class="toolbar">
				<button class="btn preset-tonal-surface font-semibold" onclick={discard} disabled={busy}
					>{$t('Discard')}</button
				>
				{#if batch.status === 'failed'}
					<button class="btn preset-tonal-surface font-semibold" onclick={retry} disabled={busy}
						>{$t('Retry')}</button
					>
				{/if}
				<button
					class="btn preset-filled-primary-700-300 font-semibold"
					onclick={commit}
					disabled={busy || batch.status !== 'ready'}>{$t('Commit')}</button
				>
			</div>
		</div>
		{#if batch.status === 'pending'}
			<p
				class="rounded-base border border-success-200 preset-tonal-success px-4 py-3 text-success-900"
				role="status"
			>
				{$t('Preparing uploaded PDFs…')}
			</p>
		{:else if batch.status === 'committed'}
			<p
				class="rounded-base border border-success-200 preset-tonal-success px-4 py-3 text-success-900"
				role="status"
			>
				{$t('This Import Batch has already been committed.')}
			</p>
		{/if}
		{#each previewRecords as record (record)}
			<div class="item-row">
				<strong><RichText html={String(record.title ?? $t('Untitled'))} /></strong>
				<span class="text-surface-600">{String(record.authors ?? record.doi ?? '')}</span>
				{#if record.original_name}<span class="text-surface-600"
						>{String(record.original_name)}</span
					>{/if}
			</div>
		{/each}
		{#if previewPageCount > 1}
			<nav class="pagination" aria-label={$t('Import preview pages')}>
				<button
					class="btn preset-tonal-surface font-semibold"
					disabled={previewPage === 1}
					onclick={() => (previewPage -= 1)}>{$t('Previous')}</button
				>
				<span>{$t('Page')} {previewPage} / {previewPageCount}</span>
				<button
					class="btn preset-tonal-surface font-semibold"
					disabled={previewPage === previewPageCount}
					onclick={() => (previewPage += 1)}>{$t('Next')}</button
				>
			</nav>
		{/if}
		{#if batch.errors.length}
			<h3>{$t('Diagnostics')}</h3>
		{/if}
		{#each batch.errors as diagnostic (diagnostic)}
			<div class="grid gap-1 text-error-700">
				<strong>{String(diagnostic.message ?? diagnostic.code)}</strong>
				{#if diagnostic.filename}<span>{String(diagnostic.filename)}</span>{/if}
				{#if diagnostic.row || diagnostic.code}<small
						>{diagnostic.row ? `${$t('Row')} ${String(diagnostic.row)} · ` : ''}{String(
							diagnostic.code ?? ''
						)}</small
					>{/if}
			</div>
		{/each}
	</section>
{/if}
