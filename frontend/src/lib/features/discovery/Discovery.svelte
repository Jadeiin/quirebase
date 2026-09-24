<script lang="ts">
	import { resolve } from '$app/paths';
	import { goto } from '$app/navigation';
	import { createQuery } from '@tanstack/svelte-query';
	import { apiErrorMessage } from '$lib/api/errors';
	import type { components } from '$lib/api/schema';
	import Badge from '$lib/design/Badge.svelte';
	import Notice from '$lib/design/Notice.svelte';
	import Pagination from '$lib/design/Pagination.svelte';
	import Panel from '$lib/design/Panel.svelte';
	import RichText from '$lib/design/RichText.svelte';
	import SectionHeader from '$lib/design/SectionHeader.svelte';
	import { discoveryProvidersQuery } from '$lib/features/discovery/queries';
	import { t } from '$lib/i18n';
	import Button from '$lib/design/Button.svelte';
	import { getWorkspaceContext } from '$lib/workspaces/context.svelte';
	import { workspaceHref } from '$lib/workspaces/href';

	type Results = components['schemas']['CandidatePageView'];
	type Candidate = components['schemas']['CandidateView'];
	type Clause = { id: number; field: string; operator: string; term: string };

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
	let searchAbort: AbortController | null = null;

	const workspace = getWorkspaceContext();
	const providers = createQuery(() => discoveryProvidersQuery(workspace.workspaceId));

	function addClause() {
		clauses.push({ id: nextClauseId++, field: 'any', operator: 'and', term: '' });
	}

	function removeClause(id: number) {
		clauses = clauses.filter((clause) => clause.id !== id);
	}

	async function search(page = 1) {
		searchAbort?.abort();
		const controller = new AbortController();
		searchAbort = controller;
		busy = true;
		error = '';
		try {
			results = await workspace.api.request('POST', '/workspaces/{workspace_id}/discovery/search', {
				body: {
					provider,
					clauses: clauses.map(({ field, operator, term }) => ({ field, operator, term })),
					page,
					per_page: 20,
					sort,
					year_from: yearFrom ? Number(yearFrom) : null,
					year_to: yearTo ? Number(yearTo) : null
				},
				signal: controller.signal
			});
		} catch (reason) {
			if (controller.signal.aborted) return;
			error = apiErrorMessage(reason, $t('Search failed'));
		} finally {
			if (searchAbort === controller) {
				searchAbort = null;
				busy = false;
			}
		}
	}

	async function review(candidate: Candidate) {
		const key = `${candidate.identifier_provider}:${candidate.identifier}`;
		importing = key;
		error = '';
		try {
			const batch = await workspace.api.request(
				'POST',
				'/workspaces/{workspace_id}/imports/identifier',
				{
					body: { identifier: candidate.identifier, provider: candidate.identifier_provider }
				}
			);
			await goto(
				resolve(
					workspaceHref(workspace.workspaceId, `import?batch=${encodeURIComponent(batch.id)}`)
				)
			);
		} catch (reason) {
			error = apiErrorMessage(reason, $t('Import preview failed'));
		} finally {
			importing = '';
		}
	}

	const pageCount = $derived(
		results ? Math.max(1, Math.ceil(results.total / results.per_page)) : 1
	);
</script>

<SectionHeader>
	<div>
		<p class="mb-1 text-sm font-medium text-primary-700-300">{$t('External metadata')}</p>
		<h1>{$t('Discovery')}</h1>
		<p class="text-surface-600-400">
			{$t('Build a precise query, then review candidates before Import.')}
		</p>
	</div>
</SectionHeader>

<Panel
	as="form"
	class="grid grid-cols-1 gap-3"
	onsubmit={(event) => {
		event.preventDefault();
		void search();
	}}
>
	<div
		class="grid grid-cols-1 gap-3 lg:grid-cols-[minmax(12rem,1fr)_minmax(10rem,0.7fr)_9rem_9rem]"
	>
		<label class="grid grid-cols-1 gap-1">
			<span class="text-sm font-semibold">{$t('Provider')}</span>
			<select class="select" bind:value={provider}>
				{#each providers.data ?? [] as option (option.id)}
					<option value={option.id}>{option.name}</option>
				{/each}
			</select>
		</label>
		<label class="grid grid-cols-1 gap-1">
			<span class="text-sm font-semibold">{$t('Sort')}</span>
			<select class="select" bind:value={sort}>
				<option value="relevance">{$t('Relevance')}</option>
				<option value="published">{$t('Publication date')}</option>
				<option value="cited">{$t('Citation count')}</option>
			</select>
		</label>
		<label class="grid grid-cols-1 gap-1">
			<span class="text-sm font-semibold">{$t('From year')}</span>
			<input class="input" type="number" min="1000" max="9999" bind:value={yearFrom} />
		</label>
		<label class="grid grid-cols-1 gap-1">
			<span class="text-sm font-semibold">{$t('To year')}</span>
			<input class="input" type="number" min="1000" max="9999" bind:value={yearTo} />
		</label>
	</div>

	<div class="grid grid-cols-1 gap-2" aria-label={$t('Search conditions')}>
		{#each clauses as clause, index (clause.id)}
			<div class="grid grid-cols-1 gap-2 md:grid-cols-[7rem_10rem_minmax(12rem,1fr)_auto]">
				<select class="select" bind:value={clause.operator} aria-label={$t('Boolean operator')}>
					<option value="and">{$t('AND')}</option>
					<option value="or">{$t('OR')}</option>
					<option value="not">{$t('NOT')}</option>
				</select>
				<select class="select" bind:value={clause.field} aria-label={$t('Search field')}>
					<option value="any">{$t('Any field')}</option>
					<option value="title">{$t('Title')}</option>
					<option value="author">{$t('Author')}</option>
					<option value="publication">{$t('Publication')}</option>
					<option value="abstract">{$t('Abstract')}</option>
				</select>
				<input
					class="input"
					bind:value={clause.term}
					placeholder={index === 0 ? $t('Title, author, DOI, or topic') : $t('Another condition')}
					required
				/>
				<Button
					type="button"
					disabled={clauses.length === 1}
					onclick={() => removeClause(clause.id)}>{$t('Remove')}</Button
				>
			</div>
		{/each}
	</div>
	<div class="flex flex-wrap items-center gap-2">
		<Button type="button" disabled={clauses.length >= 5} onclick={addClause}
			>{$t('Add condition')}</Button
		>
		<span class="grow basis-64"></span>
		<Button variant="filled" disabled={busy || providers.isPending}
			>{busy ? $t('Searching…') : $t('Search Discovery')}</Button
		>
	</div>
</Panel>

{#if error}<Notice variant="error" class="mt-4">{error}</Notice>{/if}

<Panel class="mt-4">
	<SectionHeader>
		<div>
			<h2>{$t('Candidate Records')}</h2>
			{#if results}<p class="text-surface-600-400">
					{$t('{count, plural, one {# result} other {# results}}', {
						count: results.total
					})}
				</p>{/if}
		</div>
	</SectionHeader>
	{#each results?.results ?? [] as candidate (`${candidate.provider}:${candidate.identifier_provider}:${candidate.identifier}`)}
		<article class="border-b border-surface-300-700 py-5 last:border-0">
			<div class="flex flex-wrap items-start justify-between gap-4">
				<div class="min-w-0 flex-1">
					<div class="flex flex-wrap items-center gap-2">
						<h3 class="mb-1 text-lg"><RichText html={candidate.title} /></h3>
						{#if candidate.imported}<Badge variant="success">{$t('Already in Library')}</Badge>{/if}
					</div>
					<p class="mb-1 text-sm text-surface-700-300">
						{candidate.authors ?? $t('Unknown contributors')}
					</p>
					<p class="mb-2 text-sm text-surface-600-400">
						{candidate.publication_title ?? $t('Unknown publication')}
						{#if candidate.publication_date}
							· {candidate.publication_date}{/if}
					</p>
					{#if candidate.abstract}
						<div class="line-clamp-3 text-sm text-surface-700-300">
							<RichText html={candidate.abstract} />
						</div>
					{/if}
					<code class="mt-2 inline-block text-xs"
						>{candidate.identifier_provider}:{candidate.identifier}</code
					>
				</div>
				{#if !candidate.imported}
					<Button variant="filled" disabled={importing !== ''} onclick={() => review(candidate)}
						>{importing === `${candidate.identifier_provider}:${candidate.identifier}`
							? $t('Preparing…')
							: $t('Review and import')}</Button
					>
				{/if}
			</div>
		</article>
	{:else}
		<p class="text-surface-600-400">{$t('Search results will appear here.')}</p>
	{/each}
	{#if results && pageCount > 1}
		<Pagination
			page={results.page}
			{pageCount}
			{busy}
			label={$t('Discovery result pages')}
			onPage={(next) => void search(next)}
		/>
	{/if}
</Panel>
