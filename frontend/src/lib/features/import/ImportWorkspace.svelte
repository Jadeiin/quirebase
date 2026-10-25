<script lang="ts">
	import { bibliographyFormats } from '#lib/export-preferences.js';
	import { resolve } from '$app/paths';
	import { beforeNavigate, goto } from '$app/navigation';
	import { page } from '$app/state';
	import { createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { onDestroy, untrack } from 'svelte';
	import { SvelteSet } from 'svelte/reactivity';
	import { Tabs } from '@skeletonlabs/skeleton-svelte';
	import { ApiError } from '#lib/api/client.js';
	import { apiErrorMessage } from '#lib/api/errors.js';
	import type { components } from '#lib/api/schema.js';
	import Panel from '#lib/design/Panel.svelte';
	import Button from '#lib/design/Button.svelte';
	import Notice from '#lib/design/Notice.svelte';
	import Badge from '#lib/design/Badge.svelte';
	import FilePicker from '#lib/design/FilePicker.svelte';
	import Icon from '#lib/design/Icon.svelte';
	import LoadingState from '#lib/design/LoadingState.svelte';
	import QueryError from '#lib/design/QueryError.svelte';
	import ImportBatchPreview from '#lib/features/import/ImportBatchPreview.svelte';
	import ImportSourceForm from '#lib/features/import/ImportSourceForm.svelte';
	import { discoveryProvidersQuery } from '#lib/features/discovery/queries.js';
	import ItemMetadataForm from '#lib/features/item/ItemMetadataForm.svelte';
	import { libraryHref } from '#lib/features/library/filters.js';
	import { getWorkflowCenter } from '#lib/features/workflows/center.svelte.js';
	import { invalidateLibrary } from '#lib/query/invalidation.js';
	import { msg, t } from '#lib/i18n.js';
	import { randomUUID } from '#lib/uuid.js';
	import { getWorkspaceContext } from '#lib/workspaces/context.svelte.js';
	import { workspaceHref } from '#lib/workspaces/href.js';
	import { confirmImportBatch } from './confirmation.js';
	import { deleteImportBatch } from './mutations.js';
	import { importReturnHref } from './list-state.js';
	import {
		importBatchQuery,
		importBatchResponseWriter,
		importKeys,
		readImportBatch,
		type ImportBatch
	} from './queries.js';

	const identifierExamples = [
		'10.1073/pnas.92.6.2288',
		'https://pubmed.ncbi.nlm.nih.gov/11607519/',
		'arXiv:2304.08030',
		'ISBN:0674016394'
	].join('\n');
	let identifiers = $state('');
	let sourceTab = $state('identifiers');
	// Keep the metadata editor lazy, then retain its draft across source tab switches.
	let manualMounted = $state(false);
	let bibliographyText = $state('');
	let bibliographyFile = $state<File | null>(null);
	let bibliographyFormat = $state('auto');
	let provider = $state('auto');
	let error = $state('');
	let navigationFailed = $state(false);
	let previewPage = $state(1);
	let metadataErrors = $state<components['schemas']['ErrorField'][]>([]);
	let pdfFiles = $state<File[]>([]);
	const pendingCommands = new SvelteSet<string>();
	const uncertainConfirmations = new SvelteSet<string>();
	const trackedWorkflows = new SvelteSet<string>();
	const queryClient = useQueryClient();
	const workspace = getWorkspaceContext();
	const { workspaceId } = workspace;
	const workflows = getWorkflowCenter();
	const batchId = $derived(page.url.searchParams.get('batch') ?? '');
	const providers = createQuery(() => ({
		...discoveryProvidersQuery(workspaceId),
		enabled: !batchId && workspace.can('item.create')
	}));
	const preview = createQuery(() => importBatchQuery(workspaceId, batchId));
	const batch = $derived(preview.data?.id === batchId ? preview.data : null);
	const hasStagedBatch = $derived(Boolean(batchId) && batch?.status !== 'committed');
	const busy = $derived(pendingCommands.has('source') || pendingCommands.has(`batch:${batchId}`));
	const confirmationUnknown = $derived(uncertainConfirmations.has(batchId));
	const previewUnavailable = $derived(
		preview.isError || preview.fetchStatus === 'paused' || preview.data === null
	);
	const currentStep = $derived(!batchId ? 1 : batch?.status === 'committed' ? 3 : 2);
	const identifierEntries = $derived(
		identifiers
			.split(/\r\n?|\n/)
			.map((value) => value.trim())
			.filter(Boolean)
	);
	const emptyMetadata: components['schemas']['ItemDetailView']['metadata'] = {
		id: `urn:uuid:${randomUUID()}`,
		type: 'Document',
		title: ''
	};
	let mounted = true;
	let navigationVersion = 0;
	let previousBatchId: string | undefined;
	let shownBatchId = '';
	beforeNavigate(() => navigationVersion++);
	onDestroy(() => {
		mounted = false;
	});

	function origin() {
		return { url: page.url, version: navigationVersion };
	}
	function isCurrent(started: ReturnType<typeof origin>) {
		return mounted && page.url === started.url && navigationVersion === started.version;
	}
	$effect(() => {
		if (batchId === previousBatchId) return;
		previousBatchId = batchId;
		shownBatchId = '';
		error = '';
		navigationFailed = false;
		previewPage = 1;
		if (batchId) {
			// Entering a preview destroys the source pickers, so retire their file state too.
			bibliographyFile = null;
			pdfFiles = [];
		}
	});
	$effect(() => {
		const next = batch;
		if (!next) return;
		untrack(() => {
			if (shownBatchId !== next.id) {
				shownBatchId = next.id;
				sourceTab =
					next.file_format === 'pdf'
						? 'pdfs'
						: next.file_format === 'metadata'
							? 'identifiers'
							: 'bibliography';
			}
			if (next.status === 'committed') uncertainConfirmations.delete(next.id);
			trackBatch(next);
		});
	});
	$effect(() => {
		if (
			providers.data &&
			provider !== 'auto' &&
			!providers.data.lookup.some((option) => option.id === provider)
		)
			provider = 'auto';
	});

	function stepChipClass(index: number): string {
		const base =
			'grid size-6 shrink-0 grid-cols-1 place-items-center rounded-full text-xs font-bold';
		if (index + 1 === currentStep)
			return `${base} bg-primary-700-300 text-primary-contrast-700-300`;
		if (index + 1 < currentStep) return `${base} bg-primary-50-950 text-primary-800-200`;
		return `${base} bg-surface-200-800 text-surface-600-400`;
	}
	function trackBatch(next: ImportBatch) {
		if (next.status !== 'pending' || !next.workflow_id || trackedWorkflows.has(next.workflow_id))
			return;
		trackedWorkflows.add(next.workflow_id);
		const refresh = () => queryClient.invalidateQueries({ queryKey: importKeys.all(workspaceId) });
		void workflows
			.track(next.workflow_id, {
				workspaceId,
				target: { kind: 'import_batch', id: next.id },
				label: $t('Import processing'),
				successMessage: msg('Import preview is ready'),
				failureMessage: msg('Import processing failed')
			})
			.settled.then(refresh, refresh);
	}
	async function acceptBatch(
		next: ImportBatch,
		started: ReturnType<typeof origin>,
		cacheBatch?: (batch: ImportBatch) => boolean
	) {
		const writeBatch = cacheBatch ?? (await importBatchResponseWriter(queryClient, workspaceId));
		if (!writeBatch(next)) return;
		void queryClient.invalidateQueries({ queryKey: importKeys.lists(workspaceId) });
		trackBatch(next);
		if (!isCurrent(started)) return;
		const url = new URL(page.url.href);
		url.searchParams.set('batch', next.id);
		// eslint-disable-next-line svelte/no-navigation-without-resolve -- page.url is already a resolved pathname
		await goto(url, { replace: true, reset: false, state: page.state });
	}
	async function importIdentifiers() {
		if (!workspace.can('item.create') || !providers.data || busy || hasStagedBatch) return;
		const started = origin();
		pendingCommands.add('source');
		error = '';
		try {
			await acceptBatch(
				await workspace.api.request('POST', '/workspaces/{workspace_id}/imports/identifiers', {
					body: { identifiers: identifierEntries, provider }
				}),
				started
			);
		} catch (reason) {
			if (isCurrent(started)) error = apiErrorMessage(reason, $t('Import preview failed'));
		} finally {
			pendingCommands.delete('source');
		}
	}
	async function upload(event: Event, kind: 'bibliography' | 'pdfs') {
		if (!workspace.can('item.create') || busy || hasStagedBatch) return;
		const started = origin();
		const form = event.currentTarget as HTMLFormElement;
		pendingCommands.add('source');
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
			await acceptBatch(uploaded, started);
		} catch (reason) {
			if (isCurrent(started)) error = apiErrorMessage(reason, $t('Upload failed'));
		} finally {
			pendingCommands.delete('source');
		}
	}
	function setBibliographyFiles(files: File[]) {
		bibliographyFile = files[0] ?? null;
	}
	async function retry() {
		if (!batch || busy || !workspace.can('item.create')) return;
		const snapshot = batch;
		const started = origin();
		const key = `batch:${snapshot.id}`;
		pendingCommands.add(key);
		error = '';
		try {
			const cacheBatch = await importBatchResponseWriter(queryClient, workspaceId, snapshot.id);
			await acceptBatch(
				await workspace.api.request('POST', '/workspaces/{workspace_id}/imports/{batch_id}/retry', {
					params: { path: { batch_id: snapshot.id } }
				}),
				started,
				cacheBatch
			);
		} catch (reason) {
			if (isCurrent(started)) error = apiErrorMessage(reason, $t('Unable to retry Import'));
		} finally {
			pendingCommands.delete(key);
		}
	}
	async function completed(next: ImportBatch, started: ReturnType<typeof origin>) {
		uncertainConfirmations.delete(next.id);
		// Cache refresh and navigation cannot change an authoritative successful confirmation.
		void invalidateLibrary(queryClient, workspaceId);
		void queryClient.invalidateQueries({ queryKey: importKeys.lists(workspaceId) });
		if (!isCurrent(started)) return;
		error = '';
		try {
			await goto(resolve(libraryHref(workspaceId, { import_batch: next.id })));
		} catch {
			if (mounted && page.url === started.url) navigationFailed = true;
		}
	}
	async function commit(basicSourceIds: string[]) {
		if (
			!batch ||
			batch.status !== 'ready' ||
			busy ||
			confirmationUnknown ||
			previewUnavailable ||
			!workspace.can('item.create')
		)
			return;
		const snapshot = batch;
		const started = origin();
		const key = `batch:${snapshot.id}`;
		pendingCommands.add(key);
		error = '';
		try {
			const result = await confirmImportBatch(queryClient, workspaceId, snapshot, basicSourceIds);
			if (result.status === 'committed') await completed(result.batch, started);
			else if (result.status === 'unknown') uncertainConfirmations.add(snapshot.id);
			else if (isCurrent(started))
				error = apiErrorMessage(result.error, $t('Unable to commit Import'));
		} finally {
			pendingCommands.delete(key);
		}
	}
	async function checkStatus() {
		if (!batchId || busy) return;
		const id = batchId;
		const started = origin();
		const key = `batch:${id}`;
		pendingCommands.add(key);
		try {
			const latest = await readImportBatch(queryClient, workspaceId, id);
			uncertainConfirmations.delete(id);
			if (latest.status === 'committed') await completed(latest, started);
		} catch {
			uncertainConfirmations.add(id);
		} finally {
			pendingCommands.delete(key);
		}
	}
	async function returnFromPreview() {
		const href =
			!workspace.can('item.create') &&
			!['history', 'discovery'].includes(page.url.searchParams.get('from') ?? '')
				? workspaceHref(workspaceId, 'import/history')
				: importReturnHref(workspaceId, page.url.searchParams);
		await goto(resolve(href), {
			reset: false,
			state: page.state
		});
	}
	async function discard() {
		if (!batch || busy || confirmationUnknown || !workspace.can('item.create')) return;
		const snapshot = batch;
		const started = origin();
		const key = `batch:${snapshot.id}`;
		pendingCommands.add(key);
		error = '';
		try {
			await deleteImportBatch(queryClient, workspaceId, snapshot.id);
			if (!isCurrent(started)) return;
			await goto(resolve(importReturnHref(workspaceId, started.url.searchParams)), {
				replace: true,
				reset: false,
				state: page.state
			});
		} catch (reason) {
			if (isCurrent(started))
				error = apiErrorMessage(
					reason,
					snapshot.status === 'committed'
						? $t('Unable to delete import record')
						: $t('Unable to discard Import')
				);
		} finally {
			pendingCommands.delete(key);
		}
	}
	async function createItem(
		metadata: components['schemas']['ItemDetailView']['metadata'],
		citationKey: string
	) {
		if (!workspace.can('item.create') || busy || hasStagedBatch) return;
		const started = origin();
		pendingCommands.add('source');
		error = '';
		metadataErrors = [];
		try {
			const item = await workspace.api.request('POST', '/workspaces/{workspace_id}/items', {
				body: { metadata, citation_key: citationKey || null }
			});
			void invalidateLibrary(queryClient, workspaceId);
			if (isCurrent(started)) await goto(resolve(workspaceHref(workspaceId, `item/${item.id}`)));
		} catch (reason) {
			if (isCurrent(started)) {
				metadataErrors = reason instanceof ApiError ? reason.fields : [];
				error = apiErrorMessage(reason, $t('Unable to create Item'));
			}
		} finally {
			pendingCommands.delete('source');
		}
	}
</script>

<div class="mb-7 flex flex-wrap items-end justify-between gap-4">
	<div>
		{#if !batchId}<p
				class="mb-2 text-xs font-bold tracking-[0.12em] text-primary-700-300 uppercase"
			>
				{$t('Add to Library')}
			</p>{/if}
		<h1 class="mb-2">{$t('Import')}</h1>
		{#if !batchId}<p class="mb-0 max-w-2xl text-surface-600-400">
				{$t('Import from identifiers, bibliography files or PDFs, or create an Item manually.')}
			</p>{/if}
	</div>
	{#if batchId}
		<Button onclick={returnFromPreview}
			>{page.url.searchParams.get('from') === 'discovery'
				? $t('Back to Discovery')
				: page.url.searchParams.get('from') === 'history'
					? $t('Back to import history')
					: workspace.can('item.create')
						? $t('New import')
						: $t('Import history')}</Button
		>
	{:else}
		<Button as="a" href={resolve(workspaceHref(workspaceId, 'import/history'))}
			>{$t('Import history')}</Button
		>
	{/if}
</div>
<ol
	class="mb-5 grid list-none grid-cols-3 gap-3 border-b border-surface-300-700 p-0 pb-4 sm:flex sm:gap-6"
>
	{#each [{ number: '1', title: $t('Choose a source') }, { number: '2', title: $t('Preview records') }, { number: '3', title: $t('Import to Library') }] as step, index (step.number)}
		<li
			class="flex min-w-0 items-center gap-2"
			aria-current={index + 1 === currentStep ? 'step' : undefined}
		>
			<span class={stepChipClass(index)}
				>{#if index + 1 < currentStep}<Icon name="check" size={13} />{:else}{step.number}{/if}</span
			>
			<span
				class="text-xs leading-4 sm:text-sm"
				class:font-semibold={index + 1 === currentStep}
				class:text-surface-600-400={index + 1 !== currentStep}>{step.title}</span
			>
		</li>
	{/each}
</ol>
{#if error}<Notice variant="error">{error}</Notice>{/if}
{#if confirmationUnknown}
	<Notice variant="warning" as="div" class="flex flex-wrap items-center justify-between gap-3">
		<span
			>{$t(
				'We could not confirm whether the import completed. Check its status before trying again.'
			)}</span
		>
		<Button disabled={busy} onclick={checkStatus}>{$t('Check import status')}</Button>
	</Notice>
{:else if batchId && previewUnavailable}
	<QueryError
		message={apiErrorMessage(preview.error, $t('Unable to load Import preview'))}
		busy={preview.isFetching}
		onRetry={() => void preview.refetch()}
	/>
{/if}
{#if navigationFailed}
	<Notice variant="warning"
		>{$t('Import succeeded. Use View imported Items to open the result.')}</Notice
	>
{/if}
{#if !batchId && workspace.can('item.create')}
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
					class="flex items-center gap-2 whitespace-nowrap data-selected:text-primary-800-200"
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
				description={$t('Paste up to 50 identifiers, one per line.')}
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
				description={$t('Upload a bibliography file or paste bibliography data.')}
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
						disabled={busy || hasStagedBatch}
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
				title={$t('Import PDFs')}
				description={$t('Look up DOI or arXiv IDs from PDFs and import them together.')}
				busy={busy || hasStagedBatch}
				submitLabel={$t('Preview import')}
				submitDisabled={pdfFiles.length === 0}
				onsubmit={(event) => {
					event.preventDefault();
					void upload(event, 'pdfs');
				}}
			>
				<div class="grid min-w-0 grid-cols-1 gap-3">
					<FilePicker
						name="pdfs"
						label={$t('PDF files')}
						hint={$t('Drop PDFs here or choose files. You can add more.')}
						actionLabel={$t('Choose files')}
						accept={['application/pdf', '.pdf']}
						multiple
						maxFiles={50}
						required={pdfFiles.length === 0}
						disabled={busy || hasStagedBatch}
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
							<h2 class="mb-1">{$t('New Item')}</h2>
							<p class="mb-0 text-sm text-surface-600-400">
								{$t('Enter Item metadata manually.')}
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
{#if batchId && preview.isPending && preview.fetchStatus !== 'paused'}
	<LoadingState label={$t('Loading Import preview…')} />
{:else if batch}
	{#key batch.id}
		<ImportBatchPreview
			{batch}
			canCommit={workspace.can('item.create')}
			page={previewPage}
			busy={busy || confirmationUnknown || previewUnavailable}
			resultHref={libraryHref(workspaceId, { import_batch: batch.id })}
			onDiscard={discard}
			onDeleteImportRecord={discard}
			onRetry={retry}
			onCommit={commit}
			onPage={(next) => (previewPage = next)}
		/>
	{/key}
{/if}
