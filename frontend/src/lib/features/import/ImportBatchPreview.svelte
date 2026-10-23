<script lang="ts">
	import { SvelteSet } from 'svelte/reactivity';
	import { resolve } from '$app/paths';
	import Badge from '#lib/design/Badge.svelte';
	import Button from '#lib/design/Button.svelte';
	import EmptyState from '#lib/design/EmptyState.svelte';
	import Icon from '#lib/design/Icon.svelte';
	import LoadingState from '#lib/design/LoadingState.svelte';
	import Pagination from '#lib/design/Pagination.svelte';
	import Panel from '#lib/design/Panel.svelte';
	import type { components } from '#lib/api/schema.js';
	import { domainLabel } from '#lib/domain-labels.js';
	import { t } from '#lib/i18n.js';
	import type { WorkspacePath } from '#lib/workspaces/href.js';
	import ImportCandidateRow from './ImportCandidateRow.svelte';

	type ImportBatch = components['schemas']['ImportBatchPreview'];
	type ImportDiagnostic = components['schemas']['ImportDiagnostic'];

	let {
		batch,
		page,
		busy,
		canCommit,
		resultHref,
		onDiscard,
		onDeleteReceipt,
		onRetry,
		onCommit,
		onPage
	}: {
		batch: ImportBatch;
		page: number;
		busy: boolean;
		canCommit: boolean;
		resultHref: WorkspacePath;
		onDiscard: () => void;
		onDeleteReceipt: () => void;
		onRetry: () => void;
		onCommit: (basicSourceIds: string[]) => void;
		onPage: (page: number) => void;
	} = $props();

	let pageSize = $state(20);
	const selectedBasicSources = new SvelteSet<string>();
	const basicRecords = $derived(batch.records.filter((record) => record.is_basic));
	const selectedBasicIds = $derived(
		basicRecords.flatMap((record) =>
			record.source && selectedBasicSources.has(record.source.id) ? [record.source.id] : []
		)
	);
	const importCount = $derived(
		batch.records.length - basicRecords.length + selectedBasicIds.length
	);
	const skippedCount = $derived(basicRecords.length - selectedBasicIds.length);
	$effect(() => {
		if (batch.status !== 'ready') selectedBasicSources.clear();
	});
	const records = $derived(batch.records.slice((page - 1) * pageSize, page * pageSize));
	const pageCount = $derived(Math.max(1, Math.ceil(batch.records.length / pageSize)));
	const statusVariants = {
		pending: 'warning',
		ready: 'success',
		failed: 'error',
		committed: 'success'
	} as const satisfies Record<ImportBatch['status'], 'warning' | 'success' | 'error'>;
	const statusVariant = $derived(statusVariants[batch.status]);
	const identifiedCount = $derived(batch.records.length - basicRecords.length);
	const identifiedRecords = $derived(records.filter((record) => !record.is_basic));
	const basicPageRecords = $derived(records.filter((record) => record.is_basic));
	const errors = $derived(batch.errors.filter((row) => row.severity !== 'warning'));
	const warnings = $derived(
		batch.errors.filter((row) => row.severity === 'warning' && !isBasicDiagnostic(row))
	);

	function isBasicDiagnostic(diagnostic: ImportDiagnostic): boolean {
		return (
			['missing_identifier', 'metadata_not_found'].includes(diagnostic.code ?? '') &&
			basicRecords.some((record) => record.source?.original_name === diagnostic.filename)
		);
	}
	function basicReason(record: ImportBatch['records'][number]): string {
		const diagnostics = batch.errors.filter((row) => row.filename === record.source?.original_name);
		if (diagnostics.length === 1) {
			if (diagnostics[0].code === 'missing_identifier') return $t('No DOI or arXiv ID found');
			if (diagnostics[0].code === 'metadata_not_found') return $t('No matching metadata found');
		}
		return $t('Metadata not identified');
	}
	function selectAllBasic(selected: boolean) {
		for (const record of basicRecords) {
			if (!record.source) continue;
			if (selected) selectedBasicSources.add(record.source.id);
			else selectedBasicSources.delete(record.source.id);
		}
	}
</script>

{#snippet diagnosticContext(diagnostic: ImportDiagnostic)}
	{@const source = diagnostic.filename || diagnostic.identifier}
	{#if source || diagnostic.row != null}
		<p class="mb-1 font-medium wrap-anywhere">
			{#if source}<span>{source}</span>{/if}
			{#if source && diagnostic.row != null}<span aria-hidden="true"> · </span>{/if}
			{#if diagnostic.row != null}<span>{$t('Row {row}', { row: diagnostic.row })}</span>{/if}
		</p>
	{/if}
{/snippet}

<div class="relative">
	<Panel padding="none" class="mt-2">
		<header class="border-b border-surface-300-700 px-4 py-4">
			<div class="flex flex-wrap items-center justify-between gap-3">
				<h2 class="mb-0 text-lg">{$t('Import preview')}</h2>
				<Badge variant={statusVariant} class="shrink-0"
					>{batch.status === 'committed' ? $t('Imported') : $t(domainLabel(batch.status))}</Badge
				>
			</div>
			{#if batch.status === 'ready' && batch.records.length > 0}
				<div class="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2 text-sm text-surface-600-400">
					<span class="flex items-center gap-2"
						><span class="size-1.5 rounded-full bg-primary-700-300" aria-hidden="true"></span>{$t(
							'{count, plural, one {# ready to import} other {# ready to import}}',
							{ count: identifiedCount }
						)}</span
					>
					{#if basicRecords.length > 0}<span class="flex items-center gap-2"
							><span class="size-1.5 rounded-full bg-warning-700-300" aria-hidden="true"></span>{$t(
								'{count, plural, one {# needs metadata} other {# need metadata}}',
								{ count: basicRecords.length }
							)}</span
						>{/if}
				</div>
			{/if}
		</header>
		{#if batch.status === 'pending'}
			<div class="p-6"><LoadingState label={$t('Preparing uploaded PDFs…')} /></div>
		{:else if batch.status === 'committed'}
			<div class="p-5 sm:p-6">
				<p class="mb-3 flex items-center gap-2 font-semibold text-primary-700-300">
					<Icon name="check" size={20} />{$t(
						'Imported {count, plural, one {# record} other {# records}}',
						{ count: batch.committed_item_ids.length }
					)}
				</p>
				<p class="mb-0 text-sm text-surface-600-400">
					{$t('Import completed. Deleting this record keeps the Items and files.')}
				</p>
			</div>
		{:else if batch.records.length === 0}
			<div class="p-6">
				<EmptyState
					icon="import"
					title={$t('No records in this batch')}
					detail={$t('See the import issues below.')}
				/>
			</div>
		{/if}
		{#if identifiedRecords.length > 0}
			{#if basicRecords.length > 0}<div
					class="border-b border-surface-300-700 bg-surface-100-900 px-4 py-3"
				>
					<h3 class="mb-0 text-xs font-semibold tracking-wide text-surface-600-400">
						{$t('Identified records')}
					</h3>
				</div>{/if}
			{#each identifiedRecords as record (record)}<ImportCandidateRow {record} />{/each}
		{/if}
		{#if basicPageRecords.length > 0}
			<section aria-label={$t('PDFs without metadata')}>
				<div
					class="flex flex-wrap items-center justify-between gap-x-4 gap-y-3 border-y border-surface-300-700 bg-surface-100-900 px-4 py-4"
				>
					<div class="min-w-0">
						<h3 class="mb-1 flex items-center gap-2 text-sm">
							{$t('PDFs without metadata')}<span class="text-xs font-normal text-surface-500"
								>{basicRecords.length}</span
							>
						</h3>
						<p class="mb-0 text-xs leading-5 text-surface-600-400">
							{canCommit
								? $t('Keep the PDF now. Add its metadata after import.')
								: $t('These PDFs have no identified metadata.')}
						</p>
					</div>
					{#if canCommit}<div class="flex items-center gap-4">
							<button
								type="button"
								class="text-xs font-semibold text-primary-700-300 hover:underline disabled:text-surface-500"
								disabled={busy ||
									batch.status !== 'ready' ||
									selectedBasicIds.length === basicRecords.length}
								onclick={() => selectAllBasic(true)}>{$t('Select all')}</button
							>
							<button
								type="button"
								class="text-xs font-medium text-surface-600-400 hover:underline disabled:text-surface-500"
								disabled={busy || selectedBasicIds.length === 0}
								onclick={() => selectAllBasic(false)}>{$t('Clear selection')}</button
							>
						</div>{/if}
				</div>
				{#each basicPageRecords as record (record)}
					<ImportCandidateRow
						{record}
						selected={Boolean(record.source && selectedBasicSources.has(record.source.id))}
						selectable={canCommit}
						busy={busy || batch.status !== 'ready'}
						reason={basicReason(record)}
						onSelect={(selected) => {
							if (!record.source) return;
							if (selected) selectedBasicSources.add(record.source.id);
							else selectedBasicSources.delete(record.source.id);
						}}
					/>
				{/each}
			</section>
		{/if}
		{#if batch.records.length > 0 && pageCount > 1}<Pagination
				{page}
				{pageCount}
				{pageSize}
				total={batch.records.length}
				onPageSize={(size) => {
					pageSize = size;
					onPage(1);
				}}
				{busy}
				label={$t('Import preview pages')}
				{onPage}
			/>{/if}
		{#if errors.length > 0}
			<section class="border-t border-surface-300-700 px-4 py-4" aria-label={$t('Import issues')}>
				<h3 class="mb-3 flex items-center gap-2 text-sm">
					<span class="text-error-700-300"><Icon name="close" size={16} /></span>{$t(
						'Could not import'
					)}<span class="text-xs font-normal text-surface-500">{errors.length}</span>
				</h3>
				<ul class="m-0 grid list-none grid-cols-1 gap-3 p-0">
					{#each errors as diagnostic (diagnostic)}<li
							class="min-w-0 border-l-2 border-error-200-800 pl-3 text-sm"
						>
							{@render diagnosticContext(diagnostic)}
							<p class="mb-0 text-xs leading-5 text-surface-600-400">{diagnostic.message}</p>
						</li>{/each}
				</ul>
			</section>
		{/if}
		{#if warnings.length > 0}
			<details class="border-t border-surface-300-700 px-4 py-4">
				<summary class="cursor-pointer text-xs font-medium text-surface-600-400"
					>{$t('Import details')}<span class="ml-2 text-surface-500">{warnings.length}</span
					></summary
				>
				<ul class="mt-3 mb-0 grid list-none grid-cols-1 gap-3 p-0">
					{#each warnings as diagnostic (diagnostic)}<li
							class="min-w-0 text-xs leading-5 text-surface-600-400"
						>
							{@render diagnosticContext(diagnostic)}
							{diagnostic.message}
						</li>{/each}
				</ul>
			</details>
		{/if}
	</Panel>
	{#if canCommit || batch.status === 'committed'}
		<footer
			class="sticky bottom-16 z-30 mt-4 grid grid-cols-1 gap-3 rounded-container border border-surface-300-700 bg-surface-50-950 px-4 py-4 shadow-lg sm:flex sm:items-center sm:justify-between md:bottom-4"
			aria-label={$t('Import actions')}
		>
			<div
				class="flex min-w-0 flex-wrap items-baseline justify-between gap-x-4 gap-y-1 sm:block"
				aria-live="polite"
			>
				<p class="mb-0 text-sm font-semibold">
					{batch.status === 'pending'
						? $t('Preparing uploaded PDFs…')
						: batch.status === 'failed'
							? $t('Import processing failed')
							: batch.status === 'committed'
								? $t('Import completed')
								: $t('{count, plural, one {# record selected} other {# records selected}}', {
										count: importCount
									})}
				</p>
				{#if basicRecords.length > 0 && batch.status === 'ready'}<p
						class="mb-0 text-xs text-surface-600-400 sm:mt-1"
					>
						{$t('{count, plural, one {# PDF will be skipped} other {# PDFs will be skipped}}', {
							count: skippedCount
						})}
					</p>{/if}
			</div>
			<div class="flex flex-wrap items-center gap-2">
				{#if batch.status === 'committed'}
					{#if canCommit}<Button size="sm" onclick={onDeleteReceipt} disabled={busy}
							>{$t('Delete import record')}</Button
						>{/if}
					<Button as="a" variant="filled" class="flex-1 sm:flex-none" href={resolve(resultHref)}
						>{$t('View imported Items')}<Icon name="chevron-right" size={16} /></Button
					>
				{:else}
					<Button onclick={onDiscard} disabled={busy}>{$t('Discard')}</Button>
					{#if batch.status === 'failed'}<Button
							variant="filled"
							class="flex-1 sm:flex-none"
							onclick={onRetry}
							disabled={busy}>{$t('Retry')}</Button
						>
					{:else}<Button
							variant="filled"
							class="flex-1 sm:flex-none"
							onclick={() => onCommit(selectedBasicIds)}
							disabled={busy || batch.status !== 'ready' || importCount === 0}
							>{$t('Import {count, plural, one {# record} other {# records}}', {
								count: importCount
							})}<Icon name="chevron-right" size={16} /></Button
						>{/if}
				{/if}
			</div>
		</footer>
	{/if}
</div>
