<script lang="ts">
	import { untrack } from 'svelte';
	import { SvelteSet } from 'svelte/reactivity';
	import type { components } from '#lib/api/schema.js';
	import Button from '#lib/design/Button.svelte';
	import BibliographicSummary from '#lib/design/BibliographicSummary.svelte';
	import Notice from '#lib/design/Notice.svelte';
	import RichText from '#lib/design/RichText.svelte';
	import { t } from '#lib/i18n.js';
	import { candidateKey, identifiersForCandidates, type Candidate } from './search-state.js';

	let {
		data,
		selectionScope,
		canImport,
		busy,
		importing,
		onReview
	}: {
		data: components['schemas']['CandidatePageView'];
		selectionScope: string;
		canImport: boolean;
		busy: boolean;
		importing: boolean;
		onReview: (candidates: Candidate[]) => void;
	} = $props();

	const id = $props.id();
	const selected = new SvelteSet<string>();
	const expanded = new SvelteSet<string>();
	let previousScope = '';
	const disabled = $derived(busy || importing);
	const selectedCandidates = $derived(
		data.results.filter((candidate) => selected.has(candidateKey(candidate)))
	);
	const selectedImport = $derived(identifiersForCandidates(selectedCandidates));
	const tooManyOnPage = $derived(data.results.length > 50);

	$effect(() => {
		const scope = selectionScope;
		const visible = new Set(data.results.map(candidateKey));
		untrack(() => {
			if (scope !== previousScope) {
				selected.clear();
				expanded.clear();
				previousScope = scope;
			}
			for (const key of selected) if (!visible.has(key)) selected.delete(key);
			for (const key of expanded) if (!visible.has(key)) expanded.delete(key);
		});
	});

	function selectPage() {
		if (disabled || tooManyOnPage) return;
		for (const candidate of data.results) selected.add(candidateKey(candidate));
	}

	function toggleCandidate(candidate: Candidate, checked: boolean) {
		if (disabled) return;
		const key = candidateKey(candidate);
		if (checked && selected.size < 50) selected.add(key);
		else selected.delete(key);
	}

	function toggleAbstract(key: string) {
		if (expanded.has(key)) expanded.delete(key);
		else expanded.add(key);
	}
</script>

{#if canImport}
	<div
		class="mb-2 flex flex-wrap items-center gap-2 border-b border-surface-300-700 pb-3"
		role="group"
		aria-label={$t('Candidate selection')}
	>
		<span id={`${id}-select`} class="sr-only">{$t('Select')}</span>
		<Button size="sm" disabled={disabled || tooManyOnPage} onclick={selectPage}
			>{$t('Select this page')}</Button
		>
		<Button size="sm" disabled={disabled || selected.size === 0} onclick={() => selected.clear()}
			>{$t('Clear selection')}</Button
		>
		<span class="text-sm text-surface-600-400" role="status"
			>{$t('{count} selected', { count: selected.size })}</span
		>
		<Button
			size="sm"
			variant="filled"
			class="ml-auto"
			disabled={disabled || !selectedImport}
			onclick={() => onReview([...selectedCandidates])}>{$t('Review selected')}</Button
		>
	</div>
	{#if tooManyOnPage}
		<p class="mb-3 text-sm text-surface-600-400">
			{$t('Select up to 50 candidates for one import preview.')}
		</p>
	{/if}
	{#if selectedCandidates.length > 0 && !selectedImport}
		<Notice variant="warning" class="mb-3"
			>{$t('Select candidates with the same identifier type to review them together.')}</Notice
		>
	{/if}
{/if}

{#each data.results as candidate, index (candidateKey(candidate))}
	{@const key = candidateKey(candidate)}
	<article
		class="border-b border-surface-300-700 py-4 last:border-0"
		class:bg-primary-50-950={selected.has(key)}
	>
		<div class="flex min-w-0 items-start gap-3">
			{#if canImport}
				<input
					type="checkbox"
					class="mt-1 size-4 shrink-0"
					aria-labelledby={`${id}-select ${id}-title-${index}`}
					checked={selected.has(key)}
					disabled={disabled || (!selected.has(key) && selected.size >= 50)}
					onchange={(event) => toggleCandidate(candidate, event.currentTarget.checked)}
				/>
			{/if}
			<div class="min-w-0 flex-1">
				<div class="flex min-w-0 flex-wrap items-start justify-between gap-x-4 gap-y-2">
					<div class="min-w-0 flex-1 basis-64">
						<BibliographicSummary density="detailed" headingId={`${id}-title-${index}`}>
							{#snippet title()}<RichText html={candidate.title} />{/snippet}
							{#snippet authors()}{candidate.authors ?? $t('Unknown authors')}{/snippet}
							{candidate.publication_title ?? $t('Unknown publication')}
							{#if candidate.publication_date}
								· {candidate.publication_date}{/if}
						</BibliographicSummary>
					</div>
					{#if canImport}
						<Button size="sm" {disabled} onclick={() => onReview([candidate])}
							>{$t('Review and import')}</Button
						>
					{/if}
				</div>
				{#if candidate.abstract}
					<div
						id={`${id}-abstract-${index}`}
						class="mt-2 text-sm wrap-anywhere text-surface-700-300"
						class:line-clamp-3={!expanded.has(key)}
					>
						<RichText html={candidate.abstract} />
					</div>
					<Button
						size="sm"
						class="mt-1"
						aria-expanded={expanded.has(key)}
						aria-controls={`${id}-abstract-${index}`}
						onclick={() => toggleAbstract(key)}
						>{expanded.has(key) ? $t('Hide abstract') : $t('Show abstract')}</Button
					>
				{/if}
				<code class="mt-2 block text-xs break-all"
					>{candidate.identifier_provider}:{candidate.identifier}</code
				>
			</div>
		</div>
	</article>
{/each}
