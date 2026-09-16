<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { createQuery } from '@tanstack/svelte-query';
	import { apiRequest } from '$lib/api/client';
	import type { components } from '$lib/api/schema';
	import RichText from '$lib/design/RichText.svelte';
	import { t } from '$lib/i18n';

	type Results = components['schemas']['CandidatePageView'];
	type Candidate = components['schemas']['CandidateView'];
	type Clause = { id: number; field: string; operator: string; term: string };
	type Provider = { id: string; name: string };

	let nextClauseId = 2;
	let provider = $state('openalex');
	let sort = $state('relevance');
	let yearFrom = $state('');
	let yearTo = $state('');
	let clauses = $state<Clause[]>([{ id: 1, field: 'any', operator: 'and', term: '' }]);
	let busy = $state(false);
	let importing = $state('');
	let error = $state('');
	let results = $state<Results | null>(null);

	const providers = createQuery(() => ({
		queryKey: ['discovery-providers'],
		queryFn: () => apiRequest<Provider[]>('/discovery/providers')
	}));

	function addClause() {
		clauses.push({ id: nextClauseId++, field: 'any', operator: 'and', term: '' });
	}

	function removeClause(id: number) {
		clauses = clauses.filter((clause) => clause.id !== id);
	}

	async function search(page = 1) {
		busy = true;
		error = '';
		try {
			results = await apiRequest<Results>('/discovery/search', {
				method: 'POST',
				body: {
					provider,
					clauses: clauses.map(({ field, operator, term }) => ({ field, operator, term })),
					page,
					per_page: 20,
					sort,
					year_from: yearFrom ? Number(yearFrom) : null,
					year_to: yearTo ? Number(yearTo) : null
				}
			});
		} catch (reason) {
			error = reason instanceof Error ? reason.message : $t('Search failed');
		} finally {
			busy = false;
		}
	}

	async function review(candidate: Candidate) {
		const key = `${candidate.identifier_provider}:${candidate.identifier}`;
		importing = key;
		error = '';
		try {
			const batch = await apiRequest<{ id: string }>('/imports/identifier', {
				method: 'POST',
				body: { identifier: candidate.identifier, provider: candidate.identifier_provider }
			});
			await goto(resolve(`/import?batch=${encodeURIComponent(batch.id)}`));
		} catch (reason) {
			error = reason instanceof Error ? reason.message : $t('Import preview failed');
		} finally {
			importing = '';
		}
	}

	function changePage(delta: number) {
		if (results) void search(results.page + delta);
	}

	const pageCount = $derived(
		results ? Math.max(1, Math.ceil(results.total / results.per_page)) : 1
	);
</script>

<div class="workspace-header">
	<div>
		<p class="eyebrow">{$t('External metadata')}</p>
		<h1>{$t('Discovery')}</h1>
		<p class="muted">{$t('Build a precise query, then review candidates before Import.')}</p>
	</div>
</div>

<form
	class="panel stack"
	onsubmit={(event) => {
		event.preventDefault();
		void search();
	}}
>
	<div class="grid gap-3 lg:grid-cols-[minmax(12rem,1fr)_minmax(10rem,0.7fr)_9rem_9rem]">
		<label class="stack gap-1">
			<span class="text-sm font-semibold">{$t('Provider')}</span>
			<select class="field" bind:value={provider}>
				{#each providers.data ?? [] as option (option.id)}
					<option value={option.id}>{option.name}</option>
				{/each}
			</select>
		</label>
		<label class="stack gap-1">
			<span class="text-sm font-semibold">{$t('Sort')}</span>
			<select class="field" bind:value={sort}>
				<option value="relevance">{$t('Relevance')}</option>
				<option value="published">{$t('Publication date')}</option>
				<option value="cited">{$t('Citation count')}</option>
			</select>
		</label>
		<label class="stack gap-1">
			<span class="text-sm font-semibold">{$t('From year')}</span>
			<input class="field" type="number" min="1000" max="9999" bind:value={yearFrom} />
		</label>
		<label class="stack gap-1">
			<span class="text-sm font-semibold">{$t('To year')}</span>
			<input class="field" type="number" min="1000" max="9999" bind:value={yearTo} />
		</label>
	</div>

	<div class="grid gap-2" aria-label={$t('Search conditions')}>
		{#each clauses as clause, index (clause.id)}
			<div class="grid gap-2 md:grid-cols-[7rem_10rem_minmax(12rem,1fr)_auto]">
				<select class="field" bind:value={clause.operator} aria-label={$t('Boolean operator')}>
					<option value="and">{$t('AND')}</option>
					<option value="or">{$t('OR')}</option>
					<option value="not">{$t('NOT')}</option>
				</select>
				<select class="field" bind:value={clause.field} aria-label={$t('Search field')}>
					<option value="any">{$t('Any field')}</option>
					<option value="title">{$t('Title')}</option>
					<option value="author">{$t('Author')}</option>
					<option value="publication">{$t('Publication')}</option>
					<option value="abstract">{$t('Abstract')}</option>
				</select>
				<input
					class="field"
					bind:value={clause.term}
					placeholder={index === 0 ? $t('Title, author, DOI, or topic') : $t('Another condition')}
					required
				/>
				<button
					type="button"
					class="button"
					disabled={clauses.length === 1}
					onclick={() => removeClause(clause.id)}>{$t('Remove')}</button
				>
			</div>
		{/each}
	</div>
	<div class="toolbar items-center">
		<button type="button" class="button" disabled={clauses.length >= 5} onclick={addClause}
			>{$t('Add condition')}</button
		>
		<span class="grow"></span>
		<button class="button button-primary" disabled={busy || providers.isPending}
			>{busy ? $t('Searching…') : $t('Search Discovery')}</button
		>
	</div>
</form>

{#if error}<p class="error mt-4" role="alert">{error}</p>{/if}

<section class="panel list-panel">
	<div class="workspace-header">
		<div>
			<h2>{$t('Candidate Records')}</h2>
			{#if results}<p class="muted">{results.total} {$t('results')}</p>{/if}
		</div>
	</div>
	{#each results?.results ?? [] as candidate (`${candidate.provider}:${candidate.identifier_provider}:${candidate.identifier}`)}
		<article class="border-b border-line py-5 last:border-0">
			<div class="flex flex-wrap items-start justify-between gap-4">
				<div class="min-w-0 flex-1">
					<div class="flex flex-wrap items-center gap-2">
						<h3 class="mb-1 text-lg"><RichText html={candidate.title} /></h3>
						{#if candidate.imported}<span class="badge text-success"
								>{$t('Already in Library')}</span
							>{/if}
					</div>
					<p class="mb-1 text-sm text-secondary">
						{candidate.authors ?? $t('Unknown contributors')}
					</p>
					<p class="mb-2 text-sm text-muted">
						{candidate.publication_title ?? $t('Unknown publication')}
						{#if candidate.publication_date}
							· {candidate.publication_date}{/if}
					</p>
					{#if candidate.abstract}
						<div class="line-clamp-3 text-sm text-secondary">
							<RichText html={candidate.abstract} />
						</div>
					{/if}
					<code class="mt-2 inline-block text-xs"
						>{candidate.identifier_provider}:{candidate.identifier}</code
					>
				</div>
				{#if !candidate.imported}
					<button
						class="button button-primary"
						disabled={importing !== ''}
						onclick={() => review(candidate)}
						>{importing === `${candidate.identifier_provider}:${candidate.identifier}`
							? $t('Preparing…')
							: $t('Review and import')}</button
					>
				{/if}
			</div>
		</article>
	{:else}
		<p class="muted">{$t('Search results will appear here.')}</p>
	{/each}
	{#if results && pageCount > 1}
		<nav class="pagination" aria-label={$t('Discovery result pages')}>
			<button class="button" disabled={busy || results.page <= 1} onclick={() => changePage(-1)}
				>{$t('Previous')}</button
			>
			<span>{$t('Page')} {results.page} / {pageCount}</span>
			<button
				class="button"
				disabled={busy || results.page >= pageCount}
				onclick={() => changePage(1)}>{$t('Next')}</button
			>
		</nav>
	{/if}
</section>
