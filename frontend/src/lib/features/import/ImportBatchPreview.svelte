<script lang="ts">
	import type { components } from '$lib/api/schema';
	import RichText from '$lib/design/RichText.svelte';
	import Panel from '$lib/design/Panel.svelte';
	import Pagination from '$lib/design/Pagination.svelte';
	import Notice from '$lib/design/Notice.svelte';
	import SectionHeader from '$lib/design/SectionHeader.svelte';
	import { domainLabel } from '$lib/domain-labels';
	import { t } from '$lib/i18n';
	import Button from '$lib/design/Button.svelte';
	import ItemRow from '$lib/design/ItemRow.svelte';

	type ImportBatch = components['schemas']['ImportBatchView'];

	let { batch, page, busy, onDiscard, onRetry, onCommit, onPage } = $props<{
		batch: ImportBatch;
		page: number;
		busy: boolean;
		onDiscard: () => void;
		onRetry: () => void;
		onCommit: () => void;
		onPage: (page: number) => void;
	}>();

	const pageSize = 20;
	const records = $derived(batch.records.slice((page - 1) * pageSize, page * pageSize));
	const pageCount = $derived(Math.max(1, Math.ceil(batch.records.length / pageSize)));
</script>

<Panel class="mt-6">
	<SectionHeader>
		<div>
			<h2>{$t('Import preview')}</h2>
			<p class="text-surface-600-400">
				{batch.records.length}
				{$t('records')} · {batch.errors.length}
				{$t('diagnostics')} · {$t(domainLabel(batch.status))}
			</p>
		</div>
		{#snippet actions()}
			<div class="flex flex-wrap gap-2">
				<Button onclick={onDiscard} disabled={busy}>{$t('Discard')}</Button>
				{#if batch.status === 'failed'}
					<Button onclick={onRetry} disabled={busy}>{$t('Retry')}</Button>
				{/if}
				<Button variant="filled" onclick={onCommit} disabled={busy || batch.status !== 'ready'}
					>{$t('Commit')}</Button
				>
			</div>
		{/snippet}
	</SectionHeader>
	{#if batch.status === 'pending'}
		<Notice variant="success">{$t('Preparing uploaded PDFs…')}</Notice>
	{:else if batch.status === 'committed'}
		<Notice variant="success">{$t('This Import Batch has already been committed.')}</Notice>
	{/if}
	{#each records as record (record)}
		<ItemRow>
			<strong><RichText html={String(record.title ?? $t('Untitled'))} /></strong>
			<span class="text-surface-600-400">{String(record.authors ?? record.doi ?? '')}</span>
			{#if record.original_name}<span class="text-surface-600-400"
					>{String(record.original_name)}</span
				>{/if}
		</ItemRow>
	{/each}
	{#if pageCount > 1}
		<Pagination {page} {pageCount} label={$t('Import preview pages')} {onPage} />
	{/if}
	{#if batch.errors.length}
		<h3>{$t('Diagnostics')}</h3>
	{/if}
	{#each batch.errors as diagnostic (diagnostic)}
		<div class="grid grid-cols-1 gap-1 text-error-700-300">
			<strong>{String(diagnostic.message ?? diagnostic.code)}</strong>
			{#if diagnostic.filename}<span>{String(diagnostic.filename)}</span>{/if}
			{#if diagnostic.row || diagnostic.code}<small
					>{diagnostic.row ? `${$t('Row')} ${String(diagnostic.row)} · ` : ''}{String(
						diagnostic.code ?? ''
					)}</small
				>{/if}
		</div>
	{/each}
</Panel>
