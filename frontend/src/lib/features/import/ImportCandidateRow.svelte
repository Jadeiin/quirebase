<script lang="ts">
	import type { components } from '#lib/api/schema.js';
	import BibliographicSummary from '#lib/design/BibliographicSummary.svelte';
	import Icon from '#lib/design/Icon.svelte';
	import RichText from '#lib/design/RichText.svelte';
	import { kilobytes, numberFormat } from '#lib/format.js';
	import { t } from '#lib/i18n.js';
	import { metadataValueLabel } from '../item/metadata-labels.js';
	import { text, object, objects, contributorName } from '../item/metadata-draft.js';

	let {
		record,
		selected = false,
		selectable = false,
		busy = false,
		reason = '',
		onSelect
	}: {
		record: components['schemas']['ImportCandidatePreview'];
		selected?: boolean;
		selectable?: boolean;
		busy?: boolean;
		reason?: string;
		onSelect?: (selected: boolean) => void;
	} = $props();
	const authorText = $derived(
		objects(record.metadata.contributors)
			.filter((row) => Array.isArray(row.roles) && row.roles.includes('Author'))
			.map(contributorName)
			.filter(Boolean)
			.join('; ')
	);
	const checkboxId = $derived(`import-source-${record.source?.id}`);
</script>

<article
	class="grid min-w-0 grid-cols-[auto_minmax(0,1fr)] items-start gap-3 border-b border-surface-300-700 px-4 py-4 transition-colors last:border-b-0"
	class:bg-primary-50-950={record.is_basic && selected}
>
	{#if record.is_basic && selectable}
		<input
			id={checkboxId}
			type="checkbox"
			class="mt-1 size-4 shrink-0"
			checked={selected}
			disabled={busy}
			aria-label={$t('Create a basic Item for {filename}', {
				filename: record.source?.original_name ?? ''
			})}
			onchange={(event) => onSelect?.(event.currentTarget.checked)}
		/>
	{:else}
		<span
			class="mt-1 grid size-4 grid-cols-1 place-items-center"
			class:text-primary-700-300={!record.is_basic}
			class:text-surface-500={record.is_basic}
			><Icon name={record.source ? 'file' : 'library'} size={16} /></span
		>
	{/if}
	<BibliographicSummary>
		{#snippet title()}
			{#if record.is_basic}
				{#if selectable}<label for={checkboxId} class="cursor-pointer"
						>{record.source?.original_name || text(record.metadata.title)}</label
					>
				{:else}{record.source?.original_name || text(record.metadata.title)}{/if}
			{:else}<RichText html={text(record.metadata.title) || $t('Untitled')} />{/if}
		{/snippet}
		{#snippet authors()}
			{#if record.is_basic}{reason || $t('Metadata not identified')}{:else}{authorText ||
					$t('Unknown authors')}{/if}
		{/snippet}
		{#if record.is_basic}
			{#if record.source?.size}{$t('{size} KB', {
					size: $numberFormat.format(kilobytes(record.source.size))
				})}{/if}
		{:else}
			<p class="mb-0">
				{#if text(object(record.metadata.container).title)}<RichText
						html={text(object(record.metadata.container).title)}
					/><span aria-hidden="true"> · </span>{/if}
				{#if record.metadata.date_published}{record.metadata.date_published}<span
						aria-hidden="true"
					>
						·
					</span>{/if}
				{metadataValueLabel(record.metadata.type)}
			</p>
			{#if record.source}<p class="mt-1 mb-0 truncate" title={record.source.original_name}>
					{record.source.original_name}
				</p>{/if}
		{/if}
	</BibliographicSummary>
</article>
