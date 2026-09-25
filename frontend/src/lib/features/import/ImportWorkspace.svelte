<script lang="ts">
	import { resolve } from '$app/paths';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { useQueryClient } from '@tanstack/svelte-query';
	import { onDestroy, onMount } from 'svelte';
	import { SvelteMap } from 'svelte/reactivity';
	import { apiErrorMessage } from '$lib/api/errors';
	import type { components } from '$lib/api/schema';
	import Panel from '$lib/design/Panel.svelte';
	import Notice from '$lib/design/Notice.svelte';
	import ImportBatchPreview from '$lib/features/import/ImportBatchPreview.svelte';
	import ImportSourceForm from '$lib/features/import/ImportSourceForm.svelte';
	import ItemMetadataForm from '$lib/features/item/ItemMetadataForm.svelte';
	import { getWorkflowCenter } from '$lib/features/workflows/center.svelte';
	import { invalidateLibrary } from '$lib/query/invalidation';
	import { msg, t } from '$lib/i18n';
	import Button from '$lib/design/Button.svelte';
	import { getWorkspaceContext } from '$lib/workspaces/context.svelte';
	import { workspaceHref } from '$lib/workspaces/href';

	type ImportBatch = components['schemas']['ImportBatchView'];

	let identifier = $state('');
	let provider = $state('auto');
	let batch = $state<ImportBatch | null>(null);
	let error = $state('');
	let busy = $state(false);
	let previewPage = $state(1);
	let manualOpen = $state(false);
	let pdfFiles = $state<File[]>([]);
	let pdfInput = $state<HTMLInputElement>();
	let pollingAbort: AbortController | null = null;
	const queryClient = useQueryClient();
	const workspace = getWorkspaceContext();
	const { workspaceId } = workspace;
	const workflows = getWorkflowCenter();
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
		pollingAbort?.abort();
		pollingAbort = null;
	}

	function acceptBatch(next: ImportBatch) {
		stopPolling();
		batch = next;
		previewPage = 1;
		if (next.status === 'pending' && next.workflow_id)
			void followWorkflow(next.id, next.workflow_id);
	}

	async function loadBatch(batchId: string) {
		busy = true;
		error = '';
		try {
			acceptBatch(
				await workspace.api.request('GET', '/workspaces/{workspace_id}/imports/{batch_id}', {
					params: { path: { batch_id: batchId } }
				})
			);
		} catch (reason) {
			error = apiErrorMessage(reason, $t('Unable to load Import preview'));
		} finally {
			busy = false;
		}
	}

	async function followWorkflow(batchId: string, workflowId: string) {
		const controller = new AbortController();
		pollingAbort = controller;
		try {
			await workflows.track(workflowId, {
				workspaceId,
				label: $t('Import processing'),
				successMessage: msg('Import processing completed'),
				failureMessage: msg('Import processing failed')
			}).settled;
		} catch (reason) {
			if (controller.signal.aborted) return;
			// The refreshed Import Batch owns the user-facing terminal diagnostic.
			void reason;
		}
		if (controller.signal.aborted || batch?.id !== batchId) return;
		try {
			const refreshed = await workspace.api.request(
				'GET',
				'/workspaces/{workspace_id}/imports/{batch_id}',
				{
					params: { path: { batch_id: batchId } }
				}
			);
			if (controller.signal.aborted || batch?.id !== batchId) return;
			acceptBatch(refreshed);
			error = '';
		} catch (reason) {
			error = apiErrorMessage(reason, $t('Unable to refresh Import preview'));
		}
	}

	async function importIdentifier() {
		if (!workspace.can('items.create')) return;
		busy = true;
		error = '';
		try {
			acceptBatch(
				await workspace.api.request('POST', '/workspaces/{workspace_id}/imports/identifier', {
					body: { identifier, provider }
				})
			);
		} catch (reason) {
			error = apiErrorMessage(reason, $t('Import preview failed'));
		} finally {
			busy = false;
		}
	}

	async function upload(event: Event, kind: 'bibliography' | 'pdfs') {
		if (!workspace.can('items.create')) return;
		const form = event.currentTarget as HTMLFormElement;
		busy = true;
		error = '';
		try {
			const body = new FormData(form);
			if (kind === 'pdfs') {
				body.delete('pdfs');
				for (const file of pdfFiles) body.append('pdfs', file);
			}
			const uploaded =
				kind === 'pdfs'
					? await workspace.api.request('POST', '/workspaces/{workspace_id}/imports/pdfs', { body })
					: await workspace.api.request('POST', '/workspaces/{workspace_id}/imports/bibliography', {
							body
						});
			acceptBatch(uploaded);
			if (kind === 'pdfs') {
				pdfFiles = [];
				if (pdfInput) pdfInput.value = '';
			}
		} catch (reason) {
			error = apiErrorMessage(reason, $t('Upload failed'));
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
		if (pdfFiles.length === 0 && pdfInput) pdfInput.value = '';
	}

	async function retry() {
		if (!batch || !workspace.can('items.create')) return;
		busy = true;
		error = '';
		try {
			const result = await workspace.api.request(
				'POST',
				'/workspaces/{workspace_id}/imports/{batch_id}/retry',
				{
					params: { path: { batch_id: batch.id } }
				}
			);
			acceptBatch({ ...batch, ...result, errors: [] });
		} catch (reason) {
			error = apiErrorMessage(reason, $t('Unable to retry Import'));
		} finally {
			busy = false;
		}
	}

	async function commit() {
		if (!batch || batch.status !== 'ready' || busy || !workspace.can('items.create')) return;
		busy = true;
		error = '';
		try {
			await workspace.api.request('POST', '/workspaces/{workspace_id}/imports/{batch_id}/commit', {
				params: { path: { batch_id: batch.id } }
			});
			stopPolling();
			await invalidateLibrary(queryClient, workspaceId);
			await goto(resolve(workspaceHref(workspaceId, 'library')));
		} catch (reason) {
			error = apiErrorMessage(reason, $t('Unable to commit Import'));
		} finally {
			busy = false;
		}
	}

	async function discard() {
		if (!batch || busy || !workspace.can('items.create')) return;
		busy = true;
		error = '';
		try {
			await workspace.api.request('DELETE', '/workspaces/{workspace_id}/imports/{batch_id}', {
				params: { path: { batch_id: batch.id } }
			});
			stopPolling();
			batch = null;
		} catch (reason) {
			error = apiErrorMessage(reason, $t('Unable to discard Import'));
		} finally {
			busy = false;
		}
	}

	async function createItem(metadata: components['schemas']['ItemMetadata-Input']) {
		if (!workspace.can('items.create')) return;
		busy = true;
		error = '';
		try {
			const item = await workspace.api.request('POST', '/workspaces/{workspace_id}/items', {
				body: metadata
			});
			await invalidateLibrary(queryClient, workspaceId);
			await goto(resolve(workspaceHref(workspaceId, `item/${item.id}`)));
		} catch (reason) {
			error = apiErrorMessage(reason, $t('Unable to create Item'));
		} finally {
			busy = false;
		}
	}

	onMount(() => {
		const batchId = page.url.searchParams.get('batch');
		if (batchId) void loadBatch(batchId);
	});
	onDestroy(stopPolling);
</script>

<div class="mb-7 flex flex-wrap items-end justify-between gap-4">
	<div>
		<p class="mb-2 text-xs font-bold tracking-[0.12em] text-primary-700-300 uppercase">
			{$t('Add to Library')}
		</p>
		<h1 class="mb-2">{$t('Import')}</h1>
		<p class="mb-0 max-w-2xl text-surface-600-400">
			{$t('Bring records into Quirebase from an identifier, a bibliography, or published PDFs.')}
		</p>
	</div>
</div>
<ol
	class="mb-5 grid list-none grid-cols-1 gap-px overflow-hidden rounded-xl border border-surface-300-700 bg-surface-300-700 p-0 sm:grid-cols-3"
>
	{#each [{ number: '1', title: $t('Choose a source'), text: $t('Identifier, file, or PDFs') }, { number: '2', title: $t('Review the preview'), text: $t('Check records and diagnostics') }, { number: '3', title: $t('Commit to Library'), text: $t('Save only when you approve') }] as step (step.number)}
		<li class="flex items-center gap-3 bg-surface-50-950 px-4 py-3">
			<span
				class="grid size-7 shrink-0 grid-cols-1 place-items-center rounded-full bg-primary-50-950 text-xs font-bold text-primary-800-200"
				>{step.number}</span
			>
			<span class="min-w-0"
				><strong class="block text-sm">{step.title}</strong><small class="text-surface-600-400"
					>{step.text}</small
				></span
			>
		</li>
	{/each}
</ol>
{#if error}<Notice variant="error">{error}</Notice>{/if}
{#if workspace.can('items.create')}<div class="grid grid-cols-1 items-start gap-4 lg:grid-cols-3">
		<ImportSourceForm
			icon="search"
			title={$t('Look up an identifier')}
			description={$t('Fetch one record from DOI, PubMed, arXiv, and other scholarly providers.')}
			{busy}
			submitLabel={$t('Preview metadata')}
			onsubmit={(event) => {
				event.preventDefault();
				importIdentifier();
			}}
		>
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
					<option value="auto">{$t('Auto detect')}</option><option value="crossref">Crossref</option
					>
					<option value="pubmed">PubMed</option><option value="arxiv">arXiv</option>
					<option value="openalex">OpenAlex</option><option value="openlibrary">Open Library</option
					>
					<option value="pmc">PMC</option><option value="nasa">NASA ADS</option><option value="ieee"
						>IEEE Xplore</option
					>
				</select></label
			>
		</ImportSourceForm>
		<ImportSourceForm
			icon="library"
			title={$t('Upload a bibliography')}
			description={$t('Stage many records from a reference manager export.')}
			{busy}
			submitLabel={$t('Preview bibliography')}
			onsubmit={(event) => {
				event.preventDefault();
				upload(event, 'bibliography');
			}}
		>
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
		</ImportSourceForm>
		<ImportSourceForm
			icon="import"
			title={$t('Import published PDFs')}
			description={$t('Extract metadata and keep the papers together in one Import Batch.')}
			{busy}
			submitLabel={$t('Stage PDFs')}
			submitDisabled={pdfFiles.length === 0}
			onsubmit={(event) => {
				event.preventDefault();
				upload(event, 'pdfs');
			}}
		>
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
			<p class="text-sm text-surface-600-400">
				{$t('Choose PDFs more than once to add them to the same batch.')}
			</p>
			{#if pdfFiles.length}<ul
					class="m-0 grid min-w-0 list-none grid-cols-1 gap-2 p-0"
					aria-live="polite"
				>
					{#each pdfFiles as file (`${file.name}:${file.size}:${file.lastModified}`)}<li
							class="flex min-w-0 items-center justify-between gap-3 rounded-lg border border-surface-300-700 px-3 py-2 text-sm"
						>
							<span class="min-w-0 flex-1 truncate" title={file.name}>{file.name}</span><Button
								class="shrink-0"
								type="button"
								onclick={() => removePdf(file)}>{$t('Remove')}</Button
							>
						</li>{/each}
				</ul>{/if}
		</ImportSourceForm>
	</div>
	<section
		class="mt-4 flex flex-wrap items-center justify-between gap-4 rounded-xl border border-dashed border-surface-400-600 bg-surface-50-950 px-5 py-4"
	>
		<div>
			<h2 class="mb-1">{$t('Create an Item manually')}</h2>
			<p class="mb-0 text-sm text-surface-600-400">
				{$t('Use the metadata editor when no import source is available.')}
			</p>
		</div>
		<Button onclick={() => (manualOpen = !manualOpen)}
			>{manualOpen ? $t('Close editor') : $t('Open metadata editor')}</Button
		>
	</section>
	{#if manualOpen}
		<Panel class="mt-4 grid grid-cols-1 gap-3">
			<div>
				<p class="mb-1 text-sm font-medium text-primary-700-300">{$t('Manual creation')}</p>
				<h2>{$t('New Item metadata')}</h2>
			</div>
			<ItemMetadataForm
				metadata={emptyMetadata}
				{busy}
				submitLabel={$t('Create Item')}
				onsubmit={createItem}
			/>
		</Panel>
	{/if}
{/if}
{#if batch}
	<ImportBatchPreview
		{batch}
		canCommit={workspace.can('items.create')}
		page={previewPage}
		{busy}
		onDiscard={discard}
		onRetry={retry}
		onCommit={commit}
		onPage={(next) => (previewPage = next)}
	/>
{/if}
