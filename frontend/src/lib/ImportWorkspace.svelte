<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { useQueryClient } from '@tanstack/svelte-query';
	import { onDestroy, onMount } from 'svelte';
	import { SvelteMap } from 'svelte/reactivity';
	import { apiRequest } from '$lib/api/client';
	import type { components } from '$lib/api/schema';
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

<div class="workspace-header">
	<div>
		<h1>{$t('Import')}</h1>
		<p class="muted">{$t('Stage metadata or PDFs, inspect the preview, then commit.')}</p>
	</div>
</div>
{#if error}<p class="error" role="alert">{error}</p>{/if}
<div class="dashboard-grid">
	<form
		class="panel stack"
		onsubmit={(event) => {
			event.preventDefault();
			importIdentifier();
		}}
	>
		<h2>{$t('Identifier')}</h2>
		<input class="field" bind:value={identifier} placeholder="DOI, PMID, arXiv ID…" required />
		<select class="field" bind:value={provider}>
			<option value="auto">{$t('Auto detect')}</option><option value="crossref">Crossref</option>
			<option value="pubmed">PubMed</option><option value="arxiv">arXiv</option>
			<option value="openalex">OpenAlex</option><option value="openlibrary">Open Library</option>
			<option value="pmc">PMC</option><option value="nasa">NASA ADS</option><option value="ieee"
				>IEEE Xplore</option
			>
		</select>
		<button class="button button-primary" disabled={busy}>{$t('Preview metadata')}</button>
	</form>
	<form
		class="panel stack"
		onsubmit={(event) => {
			event.preventDefault();
			upload(event, 'bibliography');
		}}
	>
		<h2>{$t('Bibliography file')}</h2>
		<input class="field" type="file" name="bibliography" required />
		<select class="field" name="file_format">
			<option value="bibtex">BibTeX</option><option value="biblatex">BibLaTeX</option>
			<option value="ris">RIS</option><option value="endnote">EndNote</option>
		</select>
		<button class="button button-primary" disabled={busy}>{$t('Preview bibliography')}</button>
	</form>
	<form
		class="panel stack"
		onsubmit={(event) => {
			event.preventDefault();
			upload(event, 'pdfs');
		}}
	>
		<h2>{$t('Published PDFs')}</h2>
		<input
			class="field"
			type="file"
			name="pdfs"
			accept="application/pdf,.pdf"
			multiple
			required={pdfFiles.length === 0}
			bind:this={pdfInput}
			onchange={addPdfFiles}
		/>
		<p class="muted text-sm">
			{$t('Choose PDFs more than once to add them to the same batch.')}
		</p>
		{#if pdfFiles.length}<ul class="m-0 grid list-none gap-2 p-0" aria-live="polite">
				{#each pdfFiles as file (`${file.name}:${file.size}:${file.lastModified}`)}<li
						class="flex items-center justify-between gap-3 rounded-lg border border-line px-3 py-2 text-sm"
					>
						<span class="truncate">{file.name}</span><button
							type="button"
							class="button"
							onclick={() => removePdf(file)}>{$t('Remove')}</button
						>
					</li>{/each}
			</ul>{/if}
		<button class="button button-primary" disabled={busy || pdfFiles.length === 0}
			>{$t('Stage PDFs')}</button
		>
	</form>
	<section class="panel stack">
		<h2>{$t('New Item')}</h2>
		<p class="muted">{$t('Create a bibliographic record manually without an Import Batch.')}</p>
		<button class="button button-primary" onclick={() => (manualOpen = !manualOpen)}
			>{manualOpen ? $t('Close editor') : $t('Open metadata editor')}</button
		>
	</section>
</div>
{#if manualOpen}
	<section class="panel list-panel stack">
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
	<section class="panel list-panel">
		<div class="workspace-header">
			<div>
				<h2>{$t('Import preview')}</h2>
				<p class="muted">
					{batch.records.length}
					{$t('records')} · {batch.errors.length}
					{$t('diagnostics')} · {$t(domainLabel(batch.status))}
				</p>
			</div>
			<div class="toolbar">
				<button class="button" onclick={discard} disabled={busy}>{$t('Discard')}</button>
				{#if batch.status === 'failed'}
					<button class="button" onclick={retry} disabled={busy}>{$t('Retry')}</button>
				{/if}
				<button
					class="button button-primary"
					onclick={commit}
					disabled={busy || batch.status !== 'ready'}>{$t('Commit')}</button
				>
			</div>
		</div>
		{#if batch.status === 'pending'}
			<p class="notice" role="status">{$t('Preparing uploaded PDFs…')}</p>
		{:else if batch.status === 'committed'}
			<p class="notice" role="status">{$t('This Import Batch has already been committed.')}</p>
		{/if}
		{#each previewRecords as record (record)}
			<div class="item-row">
				<strong><RichText html={String(record.title ?? $t('Untitled'))} /></strong>
				<span class="muted">{String(record.authors ?? record.doi ?? '')}</span>
				{#if record.original_name}<span class="muted">{String(record.original_name)}</span>{/if}
			</div>
		{/each}
		{#if previewPageCount > 1}
			<nav class="pagination" aria-label={$t('Import preview pages')}>
				<button class="button" disabled={previewPage === 1} onclick={() => (previewPage -= 1)}
					>{$t('Previous')}</button
				>
				<span>{$t('Page')} {previewPage} / {previewPageCount}</span>
				<button
					class="button"
					disabled={previewPage === previewPageCount}
					onclick={() => (previewPage += 1)}>{$t('Next')}</button
				>
			</nav>
		{/if}
		{#if batch.errors.length}
			<h3>{$t('Diagnostics')}</h3>
		{/if}
		{#each batch.errors as diagnostic (diagnostic)}
			<div class="error grid gap-1">
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
