<script lang="ts">
	import Badge from '#lib/design/Badge.svelte';
	import Button from '#lib/design/Button.svelte';
	import EmptyState from '#lib/design/EmptyState.svelte';
	import Icon from '#lib/design/Icon.svelte';
	import ItemRow from '#lib/design/ItemRow.svelte';
	import LoadingState from '#lib/design/LoadingState.svelte';
	import Notice from '#lib/design/Notice.svelte';
	import Pagination from '#lib/design/Pagination.svelte';
	import Panel from '#lib/design/Panel.svelte';
	import RichText from '#lib/design/RichText.svelte';
	import SectionHeader from '#lib/design/SectionHeader.svelte';
	import type { components } from '#lib/api/schema.js';
	import { domainLabel } from '#lib/domain-labels.js';
	import { t } from '#lib/i18n.js';
	import { text, objects, contributorName } from '../item/metadata-draft.js';

	type ImportBatch = components['schemas']['ImportBatchPreview'];
	type ImportDiagnostic = components['schemas']['ImportDiagnostic'];

	let {
		batch,
		page,
		busy,
		canCommit,
		onDiscard,
		onRetry,
		onCommit,
		onPage
	}: {
		batch: ImportBatch;
		page: number;
		busy: boolean;
		canCommit: boolean;
		onDiscard: () => void;
		onRetry: () => void;
		onCommit: () => void;
		onPage: (page: number) => void;
	} = $props();

	const pageSize = 20;
	const records = $derived(batch.records.slice((page - 1) * pageSize, page * pageSize));
	const pageCount = $derived(Math.max(1, Math.ceil(batch.records.length / pageSize)));
	const statusVariants = {
		pending: 'warning',
		ready: 'success',
		failed: 'error',
		committed: 'success'
	} as const satisfies Record<ImportBatch['status'], 'warning' | 'success' | 'error'>;
	const statusVariant = $derived(statusVariants[batch.status]);
	const diagnosticsVariant = $derived(
		batch.errors.some((diagnostic) => diagnostic.severity !== 'warning') ? 'error' : 'warning'
	);

	function diagnosticMeta(diagnostic: ImportDiagnostic): string {
		return [
			diagnostic.row === null || diagnostic.row === undefined
				? null
				: $t('Row {row}', { row: String(diagnostic.row) }),
			diagnostic.code
		]
			.filter((part): part is string => Boolean(part))
			.join(' · ');
	}
</script>

<Panel class="mt-6">
	<SectionHeader>
		<div>
			<h2 class="flex flex-wrap items-center gap-2">
				{$t('Import preview')}
				<Badge variant={statusVariant}>{$t(domainLabel(batch.status))}</Badge>
			</h2>
			<p class="mb-0 text-surface-600-400">
				{$t('{count, plural, one {# record} other {# records}}', {
					count: batch.records.length
				})}
				· {$t('{count, plural, one {# diagnostic} other {# diagnostics}}', {
					count: batch.errors.length
				})}
			</p>
		</div>
		{#snippet actions()}
			{#if canCommit && batch.status !== 'committed'}<div class="flex flex-wrap gap-2">
					<Button onclick={onDiscard} disabled={busy}>{$t('Discard')}</Button>
					{#if batch.status === 'failed'}
						<Button variant="primary" onclick={onRetry} disabled={busy}>{$t('Retry')}</Button>
					{/if}
					<Button
						variant="filled"
						onclick={onCommit}
						disabled={busy || batch.status !== 'ready' || batch.records.length === 0}
						>{$t('Commit')}</Button
					>
				</div>{/if}
		{/snippet}
	</SectionHeader>
	{#if batch.status === 'pending'}
		<LoadingState label={$t('Preparing uploaded PDFs…')} />
	{:else if batch.status === 'committed'}
		<Notice variant="success">{$t('This Import Batch has already been committed.')}</Notice>
	{:else if batch.records.length === 0}
		<EmptyState
			icon="import"
			title={$t('No records in this batch')}
			detail={$t('Review the diagnostics below for details.')}
		/>
	{/if}
	{#each records as record (record)}
		<ItemRow>
			<strong><RichText html={text(record.metadata.title) || $t('Untitled')} /></strong>
			<span class="text-surface-600-400">
				{objects(record.metadata.contributors)
					.filter((row) => Array.isArray(row.roles) && row.roles.includes('Author'))
					.map(contributorName)
					.join('; ') || text(record.metadata.id)}</span
			>
			{#if record.source}<span
					class="flex min-w-0 items-center gap-1.5 text-sm text-surface-600-400"
					><Icon name="file" size={14} /><span class="truncate" title={record.source.original_name}
						>{record.source.original_name}</span
					></span
				>{/if}
		</ItemRow>
	{/each}
	{#if pageCount > 1}
		<Pagination {page} {pageCount} label={$t('Import preview pages')} {onPage} />
	{/if}
	{#if batch.errors.length}
		<section class="mt-4 grid grid-cols-1 gap-3">
			<div class="flex items-center gap-2">
				<h3 class="mb-0">{$t('Diagnostics')}</h3>
				<Badge variant={diagnosticsVariant}>{batch.errors.length}</Badge>
			</div>
			<ul class="m-0 grid list-none grid-cols-1 gap-2 p-0">
				{#each batch.errors as diagnostic (diagnostic)}
					{@const meta = diagnosticMeta(diagnostic)}
					<li
						class="grid grid-cols-1 gap-1 rounded-base border border-l-4 border-surface-300-700 bg-surface-100-900 px-4 py-3"
						class:border-l-warning-700-300={diagnostic.severity === 'warning'}
						class:border-l-error-700-300={diagnostic.severity !== 'warning'}
					>
						<div class="flex flex-wrap items-center gap-x-2 gap-y-1">
							<Badge variant={diagnostic.severity === 'warning' ? 'warning' : 'error'}
								>{$t(domainLabel(diagnostic.severity))}</Badge
							>
							<strong class="min-w-0">{diagnostic.message}</strong>
						</div>
						{#if diagnostic.identifier || diagnostic.filename || meta}<div
								class="grid grid-cols-1 gap-0.5 text-sm text-surface-600-400"
							>
								{#if diagnostic.identifier}<span class="break-all">{diagnostic.identifier}</span
									>{/if}
								{#if diagnostic.filename}<span class="break-all">{String(diagnostic.filename)}</span
									>{/if}
								{#if meta}<span>{meta}</span>{/if}
							</div>{/if}
					</li>
				{/each}
			</ul>
		</section>
	{/if}
</Panel>
