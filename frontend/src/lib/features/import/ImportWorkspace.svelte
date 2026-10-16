<script lang="ts">
	import { bibliographyFormats } from '#lib/export-preferences.js';
	import { resolve } from '$app/paths';
	import { goto, replaceState } from '$app/navigation';
	import { page } from '$app/state';
	import { createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { onDestroy, onMount } from 'svelte';
	import { Tabs } from '@skeletonlabs/skeleton-svelte';
	import { ApiError } from '#lib/api/client.js';
	import { apiErrorMessage } from '#lib/api/errors.js';
	import type { components } from '#lib/api/schema.js';
	import Panel from '#lib/design/Panel.svelte';
	import Notice from '#lib/design/Notice.svelte';
	import Badge from '#lib/design/Badge.svelte';
	import FilePicker from '#lib/design/FilePicker.svelte';
	import Icon from '#lib/design/Icon.svelte';
	import ImportBatchPreview from '#lib/features/import/ImportBatchPreview.svelte';
	import ImportSourceForm from '#lib/features/import/ImportSourceForm.svelte';
	import { discoveryProvidersQuery } from '#lib/features/discovery/queries.js';
	import ItemMetadataForm from '#lib/features/item/ItemMetadataForm.svelte';
	import { getWorkflowCenter } from '#lib/features/workflows/center.svelte.js';
	import { invalidateLibrary } from '#lib/query/invalidation.js';
	import { msg, t } from '#lib/i18n.js';
	import { getWorkspaceContext } from '#lib/workspaces/context.svelte.js';
	import { workspaceHref } from '#lib/workspaces/href.js';

	type ImportBatch = components['schemas']['ImportBatchPreview'];
	const identifierExamples = [
		'10.1073/pnas.92.6.2288',
		'https://pubmed.ncbi.nlm.nih.gov/11607519/',
		'arXiv:2304.08030',
		'ISBN:0674016394'
	].join('\n');

	let identifiers = $state('');
	let sourceTab = $state('identifiers');
	// Skeleton's Tabs.Content keeps inactive panels mounted, so gate the metadata
	// editor behind first activation: mounting it starts the schema request and
	// loads the lazily imported editor even when the user never opens the tab.
	// Keep it mounted afterwards so in-progress drafts survive tab switches.
	let manualMounted = $state(false);
	let bibliographyText = $state('');
	let bibliographyFile = $state<File | null>(null);
	let bibliographyFormat = $state('auto');
	let provider = $state('auto');
	let batch = $state<ImportBatch | null>(null);
	const hasStagedBatch = $derived(batch !== null && batch.status !== 'committed');
	let error = $state('');
	let busy = $state(false);
	let previewPage = $state(1);
	let metadataErrors = $state<components['schemas']['ErrorField'][]>([]);
	let pdfFiles = $state<File[]>([]);
	let pdfPicker = $state<{ clearFiles: () => void } | null>(null);
	let pollingAbort: AbortController | null = null;
	const queryClient = useQueryClient();
	const workspace = getWorkspaceContext();
	const { workspaceId } = workspace;
	const providers = createQuery(() => discoveryProvidersQuery(workspaceId));
	const currentStep = $derived(batch === null ? 1 : batch.status === 'committed' ? 3 : 2);
	const identifierEntries = $derived(
		identifiers
			.split(/\r\n?|\n/)
			.map((value) => value.trim())
			.filter(Boolean)
	);

	function stepChipClass(index: number): string {
		const base =
			'grid size-6 shrink-0 grid-cols-1 place-items-center rounded-full text-xs font-bold';
		if (index + 1 === currentStep)
			return `${base} bg-primary-700-300 text-primary-contrast-700-300`;
		if (index + 1 < currentStep) return `${base} bg-primary-50-950 text-primary-800-200`;
		return `${base} bg-surface-200-800 text-surface-600-400`;
	}
	$effect(() => {
		if (
			providers.data &&
			provider !== 'auto' &&
			!providers.data.lookup.some((option) => option.id === provider)
		) {
			provider = 'auto';
		}
	});
	const workflows = getWorkflowCenter();
	const emptyMetadata: components['schemas']['ItemDetailView']['metadata'] = {
		id: `urn:uuid:${crypto.randomUUID()}`,
		type: 'Document',
		title: ''
	};

	function stopPolling() {
		pollingAbort?.abort();
		pollingAbort = null;
	}

	function delay(milliseconds: number, signal: AbortSignal): Promise<void> {
		return new Promise((resolveDelay, reject) => {
			if (signal.aborted) return reject(new DOMException('Import polling aborted', 'AbortError'));
			const completed = () => {
				signal.removeEventListener('abort', aborted);
				resolveDelay();
			};
			const aborted = () => {
				window.clearTimeout(timer);
				reject(new DOMException('Import polling aborted', 'AbortError'));
			};
			const timer = window.setTimeout(completed, milliseconds);
			signal.addEventListener('abort', aborted, { once: true });
		});
	}

	function acceptBatch(next: ImportBatch) {
		stopPolling();
		if (batch?.id !== next.id) {
			sourceTab =
				next.file_format === 'pdf'
					? 'pdfs'
					: next.file_format === 'metadata'
						? 'identifiers'
						: 'bibliography';
		}
		batch = next;
		previewPage = 1;
		const url = new URL(page.url.href);
		url.searchParams.set('batch', next.id);
		// eslint-disable-next-line svelte/no-navigation-without-resolve -- page.url is already a resolved pathname
		const navigation = replaceState(url, page.state);
		if (next.status === 'pending') {
			if (next.workflow_id) void followWorkflow(next.id, next.workflow_id);
			else void followBatch(next.id);
		}
		return navigation;
	}

	async function followBatch(batchId: string) {
		const controller = new AbortController();
		pollingAbort = controller;
		let interval = 500;
		try {
			for (;;) {
				await delay(interval, controller.signal);
				const refreshed = await workspace.api.request(
					'GET',
					'/workspaces/{workspace_id}/imports/{batch_id}',
					{
						params: { path: { batch_id: batchId } },
						signal: controller.signal
					}
				);
				if (controller.signal.aborted || batch?.id !== batchId) return;
				if (refreshed.status !== 'pending' || refreshed.workflow_id) {
					await acceptBatch(refreshed);
					error = '';
					return;
				}
				batch = refreshed;
				interval = Math.min(interval * 2, 4000);
			}
		} catch (reason) {
			if (controller.signal.aborted) return;
			error = apiErrorMessage(reason, $t('Unable to refresh Import preview'));
		}
	}

	async function loadBatch(batchId: string) {
		busy = true;
		error = '';
		try {
			await acceptBatch(
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
			await acceptBatch(refreshed);
			error = '';
		} catch (reason) {
			error = apiErrorMessage(reason, $t('Unable to refresh Import preview'));
		}
	}

	async function importIdentifiers() {
		if (!workspace.can('item.create') || !providers.data || busy || hasStagedBatch) return;
		busy = true;
		error = '';
		try {
			await acceptBatch(
				await workspace.api.request('POST', '/workspaces/{workspace_id}/imports/identifiers', {
					body: { identifiers: identifierEntries, provider }
				})
			);
		} catch (reason) {
			error = apiErrorMessage(reason, $t('Import preview failed'));
		} finally {
			busy = false;
		}
	}

	async function upload(event: Event, kind: 'bibliography' | 'pdfs') {
		if (!workspace.can('item.create') || busy || hasStagedBatch) return;
		const form = event.currentTarget as HTMLFormElement;
		busy = true;
		error = '';
		try {
			const body = new FormData(form);
			if (kind === 'bibliography') {
				body.delete('bibliography');
				body.set('file_format', bibliographyFormat);
				body.append(
					'bibliography',
					bibliographyFile ??
						new File([bibliographyText], 'pasted-bibliography.txt', { type: 'text/plain' })
				);
			}
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
			if (kind === 'pdfs') pdfPicker?.clearFiles();
			await acceptBatch(uploaded);
		} catch (reason) {
			error = apiErrorMessage(reason, $t('Upload failed'));
		} finally {
			busy = false;
		}
	}

	function setBibliographyFiles(files: File[]) {
		bibliographyFile = files[0] ?? null;
	}

	async function retry() {
		if (!batch || !workspace.can('item.create')) return;
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
			await acceptBatch(result);
		} catch (reason) {
			error = apiErrorMessage(reason, $t('Unable to retry Import'));
		} finally {
			busy = false;
		}
	}

	async function commit() {
		if (!batch || batch.status !== 'ready' || busy || !workspace.can('item.create')) return;
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
		if (!batch || busy || !workspace.can('item.create')) return;
		busy = true;
		error = '';
		try {
			await workspace.api.request('DELETE', '/workspaces/{workspace_id}/imports/{batch_id}', {
				params: { path: { batch_id: batch.id } }
			});
			stopPolling();
			batch = null;
			const url = new URL(page.url.href);
			url.searchParams.delete('batch');
			// eslint-disable-next-line svelte/no-navigation-without-resolve -- page.url is already a resolved pathname
			await replaceState(url, page.state);
		} catch (reason) {
			error = apiErrorMessage(reason, $t('Unable to discard Import'));
		} finally {
			busy = false;
		}
	}

	async function createItem(
		metadata: components['schemas']['ItemDetailView']['metadata'],
		citationKey: string
	) {
		if (!workspace.can('item.create') || busy || hasStagedBatch) return;
		busy = true;
		error = '';
		metadataErrors = [];
		try {
			const item = await workspace.api.request('POST', '/workspaces/{workspace_id}/items', {
				body: { metadata, citation_key: citationKey || null }
			});
			await invalidateLibrary(queryClient, workspaceId);
			await goto(resolve(workspaceHref(workspaceId, `item/${item.id}`)));
		} catch (reason) {
			metadataErrors = reason instanceof ApiError ? reason.fields : [];
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
			{$t('Add records using identifiers, bibliography files, PDFs, or the metadata editor.')}
		</p>
	</div>
</div>
<ol class="mb-6 flex list-none flex-wrap items-center p-0">
	{#each [{ number: '1', title: $t('Choose a source') }, { number: '2', title: $t('Review the preview') }, { number: '3', title: $t('Commit to Library') }] as step, index (step.number)}
		<li class="flex items-center" aria-current={index + 1 === currentStep ? 'step' : undefined}>
			<span class={stepChipClass(index)}
				>{#if index + 1 < currentStep}<Icon name="check" size={13} />{:else}{step.number}{/if}</span
			>
			<span
				class="ml-2 text-sm"
				class:font-semibold={index + 1 === currentStep}
				class:text-surface-600-400={index + 1 !== currentStep}>{step.title}</span
			>
			{#if index < 2}<span
					class="mx-3 hidden h-px w-6 bg-surface-300-700 sm:block"
					aria-hidden="true"
				></span>{/if}
		</li>
	{/each}
</ol>
{#if error}<Notice variant="error">{error}</Notice>{/if}
{#if workspace.can('item.create')}
	<Tabs
		value={sourceTab}
		onValueChange={(details) => {
			sourceTab = details.value ?? 'identifiers';
			if (sourceTab === 'manual') manualMounted = true;
		}}
	>
		<Tabs.List class="mb-4 max-w-full overflow-x-auto" aria-label={$t('Import methods')}>
			<Tabs.Indicator class="bg-primary-700-300" />
			{#each [['identifiers', 'search', $t('Identifiers')], ['bibliography', 'library', $t('Bibliography')], ['pdfs', 'import', $t('PDFs')], ['manual', 'plus', $t('Manual creation')]] as [value, icon, label] (value)}
				<Tabs.Trigger
					{value}
					class="flex items-center gap-2 whitespace-nowrap data-selected:text-primary-700-300"
				>
					<Icon name={icon} size={16} />{label}
				</Tabs.Trigger>
			{/each}
		</Tabs.List>
		{#if hasStagedBatch}
			<Notice
				>{$t('Commit or discard the current Import Batch before starting another import.')}</Notice
			>
		{/if}
		<Tabs.Content value="identifiers">
			<ImportSourceForm
				icon="search"
				title={$t('Look up identifiers')}
				description={$t(
					'Paste up to 50 identifiers, one per line. Each record is looked up separately.'
				)}
				busy={busy || hasStagedBatch || providers.isPending || providers.isError}
				submitLabel={$t('Preview metadata')}
				submitDisabled={identifierEntries.length === 0 || identifierEntries.length > 50}
				onsubmit={(event) => {
					event.preventDefault();
					void importIdentifiers();
				}}
			>
				<div class="grid min-w-0 grid-cols-1 gap-1.5">
					<div class="flex flex-wrap items-center justify-between gap-2">
						<label for="import-identifiers">{$t('Identifiers')}</label>
						<Badge
							variant={identifierEntries.length > 50 ? 'error' : 'surface'}
							class="tabular-nums"
							aria-live="polite"
						>
							{$t('{count} / 50 identifiers', { count: identifierEntries.length })}
						</Badge>
					</div>
					<textarea
						id="import-identifiers"
						class="textarea"
						bind:value={identifiers}
						rows="7"
						placeholder={identifierExamples}
						aria-describedby="import-identifiers-help"
						required></textarea>
					<p id="import-identifiers-help" class="mb-0 text-sm text-surface-600-400">
						{$t(
							'Use DOI, PMID, arXiv, ISBN, OpenAlex IDs, or their supported URLs. Prefix ISBN-10 with ISBN:.'
						)}
					</p>
				</div>
				<label
					>{$t('Data source')}<select
						class="select"
						bind:value={provider}
						disabled={providers.isPending || providers.isError}
					>
						<option value="auto">{$t('Auto detect')}</option>
						{#each providers.data?.lookup ?? [] as option (option.id)}
							<option value={option.id}>{option.name}</option>
						{/each}
					</select></label
				>
				{#if providers.isError}<Notice variant="error"
						>{apiErrorMessage(providers.error, $t('Unable to load Import options'))}</Notice
					>{/if}
			</ImportSourceForm>
		</Tabs.Content>
		<Tabs.Content value="bibliography">
			<ImportSourceForm
				icon="library"
				title={$t('Import a bibliography')}
				description={$t('Upload a reference manager export or paste structured bibliography data.')}
				busy={busy || hasStagedBatch}
				submitLabel={$t('Preview bibliography')}
				submitDisabled={!bibliographyFile && !bibliographyText.trim()}
				onsubmit={(event) => {
					event.preventDefault();
					void upload(event, 'bibliography');
				}}
			>
				<div class="grid min-w-0 grid-cols-1 gap-3">
					<FilePicker
						name="bibliography"
						label={$t('Bibliography file')}
						actionLabel={$t('Choose file')}
						accept={['.bib', '.bibtex', '.ris', '.json', 'application/json', 'text/plain']}
						disabled={hasStagedBatch}
						onFilesChange={setBibliographyFiles}
					/>
					{#if bibliographyFile}
						<p class="mb-0 text-sm text-surface-600-400">
							{$t('Remove the chosen file to paste bibliography data instead.')}
						</p>
					{:else}
						<label>
							{$t('Or paste bibliography data')}
							<textarea
								class="textarea"
								bind:value={bibliographyText}
								rows="6"
								placeholder={'@article{...}'}
								aria-describedby="bibliography-help"></textarea>
						</label>
					{/if}
					<p id="bibliography-help" class="mb-0 text-sm text-surface-600-400">
						{$t(
							'Supports BibTeX, RIS, CSL-JSON, and Commonmeta, up to 5 MiB. Formatted reference text is not supported yet.'
						)}
					</p>
				</div>
				<label
					>{$t('File format')}<select
						class="select"
						name="file_format"
						bind:value={bibliographyFormat}
					>
						<option value="auto">{$t('Auto detect')}</option>
						{#each bibliographyFormats.filter((choice) => choice.importable) as choice (choice.value)}
							<option value={choice.value}>{$t(choice.label)}</option>
						{/each}
					</select></label
				>
			</ImportSourceForm>
		</Tabs.Content>
		<Tabs.Content value="pdfs">
			<ImportSourceForm
				icon="import"
				title={$t('Import published PDFs')}
				description={$t('Extract metadata and keep the papers together in one Import Batch.')}
				busy={busy || hasStagedBatch}
				submitLabel={$t('Stage PDFs')}
				submitDisabled={pdfFiles.length === 0}
				onsubmit={(event) => {
					event.preventDefault();
					void upload(event, 'pdfs');
				}}
			>
				<div class="grid min-w-0 grid-cols-1 gap-3">
					<FilePicker
						bind:this={pdfPicker}
						name="pdfs"
						label={$t('PDF files')}
						hint={$t('Drop PDFs here or choose them; choosing more later adds to the same batch.')}
						actionLabel={$t('Choose files')}
						accept={['application/pdf', '.pdf']}
						multiple
						maxFiles={50}
						required={pdfFiles.length === 0}
						disabled={hasStagedBatch}
						onFilesChange={(files) => (pdfFiles = files)}
					/>
				</div>
			</ImportSourceForm>
		</Tabs.Content>
		<Tabs.Content value="manual">
			{#if manualMounted}
				<Panel class="grid grid-cols-1 gap-4">
					<div class="flex items-start gap-3">
						<span
							class="grid size-10 shrink-0 grid-cols-1 place-items-center rounded-lg bg-primary-50-950 text-primary-800-200"
							><Icon name="plus" size={20} /></span
						>
						<div class="min-w-0">
							<h2 class="mb-1">{$t('New Item metadata')}</h2>
							<p class="mb-0 text-sm text-surface-600-400">
								{$t('Enter metadata by hand when no import source applies.')}
							</p>
						</div>
					</div>
					<ItemMetadataForm
						metadata={emptyMetadata}
						serverErrors={metadataErrors}
						busy={busy || hasStagedBatch}
						submitLabel={$t('Create Item')}
						onsubmit={createItem}
					/>
				</Panel>
			{/if}
		</Tabs.Content>
	</Tabs>
{/if}
{#if batch}
	<ImportBatchPreview
		{batch}
		canCommit={workspace.can('item.create')}
		page={previewPage}
		{busy}
		onDiscard={discard}
		onRetry={retry}
		onCommit={commit}
		onPage={(next) => (previewPage = next)}
	/>
{/if}
