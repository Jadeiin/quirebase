<script lang="ts">
	import { afterNavigate, beforeNavigate, goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { createMutation, createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { onDestroy, untrack } from 'svelte';
	import { SvelteURLSearchParams } from 'svelte/reactivity';
	import { apiErrorMessage } from '#lib/api/errors.js';
	import type { components } from '#lib/api/schema.js';
	import Button from '#lib/design/Button.svelte';
	import DateField from '#lib/design/DateField.svelte';
	import EmptyState from '#lib/design/EmptyState.svelte';
	import LoadingState from '#lib/design/LoadingState.svelte';
	import Notice from '#lib/design/Notice.svelte';
	import Pagination from '#lib/design/Pagination.svelte';
	import Panel from '#lib/design/Panel.svelte';
	import QueryError from '#lib/design/QueryError.svelte';
	import SectionHeader from '#lib/design/SectionHeader.svelte';
	import {
		importBatchResponseWriter,
		importKeys,
		type ImportBatch
	} from '#lib/features/import/queries.js';
	import { plural, t } from 'lingui-for-svelte/macro';
	import { getWorkspaceContext } from '#lib/workspaces/context.svelte.js';
	import { workspaceHref } from '#lib/workspaces/href.js';
	import DiscoveryResults from './DiscoveryResults.svelte';
	import { discoveryProvidersQuery, discoverySearchQuery } from './queries.js';
	import {
		defaultDiscoverySearch,
		discoverySearchParameters,
		identifiersForCandidates,
		readDiscoverySearch,
		type Candidate,
		type SearchRequest
	} from './search-state.js';

	type Clause = SearchRequest['clauses'][number] & { id: number };
	const workspace = getWorkspaceContext();
	const { workspaceId } = workspace;
	const queryClient = useQueryClient();
	const submitted = $derived(readDiscoverySearch(page.url.searchParams));
	const initial = untrack(() => submitted ?? defaultDiscoverySearch());
	let nextClauseId = initial.clauses.length;
	let provider = $state(initial.provider);
	let sort = $state(initial.sort);
	let yearFrom = $state(initial.year_from?.toString() ?? '');
	let yearTo = $state(initial.year_to?.toString() ?? '');
	let clauses = $state<Clause[]>(initial.clauses.map((clause, id) => ({ ...clause, id })));
	let lastAttempt = $state<SearchRequest | null>(null);
	let validationError = $state('');
	let navigationError = $state('');
	let reviewAttempt = $state<Candidate[]>([]);
	let mounted = true;
	let navigationVersion = 0;
	let searchVersion = 0;
	let publishedHref: string | undefined;
	let previousCriteria = criteria(initial);
	const providers = createQuery(() => discoveryProvidersQuery(workspaceId));
	const results = createQuery(() => discoverySearchQuery(workspaceId, submitted));
	const attempt = createQuery(() => ({
		...discoverySearchQuery(workspaceId, lastAttempt),
		enabled: false
	}));
	const reviewMutation = createMutation(() => ({
		mutationFn: (body: components['schemas']['IdentifiersImportRequest']) =>
			workspace.api.request('POST', '/workspaces/{workspace_id}/imports/identifiers', { body })
	}));
	const selectedProvider = $derived(
		providers.data?.search.find((option) => option.id === provider)
	);
	const busy = $derived(results.isFetching || attempt.isFetching);
	const unavailable = $derived(
		results.isError || (Boolean(submitted) && results.fetchStatus === 'paused')
	);
	const attemptFailed = $derived(
		Boolean(lastAttempt) && (attempt.isError || attempt.fetchStatus === 'paused')
	);
	const maxPageSize = $derived(providers.data?.max_search_page_size ?? 100);
	const pageSizes = $derived([10, 20, 25, 50, 100].filter((size) => size <= maxPageSize));
	const pageCount = $derived(
		results.data ? Math.max(1, Math.ceil(results.data.total / results.data.per_page)) : 1
	);
	const sortLabels = $derived({
		relevance: $t`Relevance`,
		published: $t`Publication date`,
		cited: $t`Citation count`,
		updated: $t`Updated`
	});
	$effect(() => {
		if (!providers.data) return;
		if (!selectedProvider) provider = providers.data.search[0]?.id ?? '';
		else if (!selectedProvider.sorts.some((option) => option === sort))
			sort = selectedProvider.sorts[0];
	});
	function criteria(request: SearchRequest) {
		return discoverySearchParameters({ ...request, page: 1, per_page: 20 });
	}
	function restoreDraft(request: SearchRequest) {
		provider = request.provider;
		sort = request.sort;
		yearFrom = request.year_from?.toString() ?? '';
		yearTo = request.year_to?.toString() ?? '';
		clauses = request.clauses.map((clause) => ({ ...clause, id: nextClauseId++ }));
	}
	beforeNavigate(() => navigationVersion++);
	afterNavigate(({ type, to }) => {
		const current = readDiscoverySearch(page.url.searchParams) ?? defaultDiscoverySearch();
		const nextCriteria = criteria(current);
		if (
			type === 'popstate' ||
			(to?.url.href !== publishedHref && nextCriteria !== previousCriteria)
		)
			restoreDraft(current);
		previousCriteria = nextCriteria;
		publishedHref = undefined;
		lastAttempt = null;
		validationError = '';
		navigationError = '';
		if (!reviewMutation.isPending) reviewMutation.reset();
	});
	onDestroy(() => {
		mounted = false;
		if (lastAttempt)
			void queryClient.cancelQueries({
				queryKey: discoverySearchQuery(workspaceId, lastAttempt).queryKey,
				exact: true
			});
	});
	function origin() {
		return { href: page.url.href, version: navigationVersion };
	}
	function isCurrent(started: ReturnType<typeof origin>) {
		return mounted && page.url.href === started.href && navigationVersion === started.version;
	}
	async function publish(request: SearchRequest, replace = false) {
		const target = resolve(
			workspaceHref(workspaceId, `discovery?${discoverySearchParameters(request)}`)
		);
		publishedHref = new URL(target, page.url.href).href;
		if (publishedHref === page.url.href) {
			lastAttempt = null;
			return;
		}
		try {
			await goto(target, { reset: false, replace });
		} catch {
			publishedHref = undefined;
			navigationError = $t`Unable to open the search results. Try again.`;
		}
	}
	// A Provider can return a smaller page or a corrected page number.
	$effect(() => {
		const data = results.data;
		if (!submitted || !data || results.isFetching || results.isError) return;
		if (submitted.page === data.page && submitted.per_page === data.per_page) return;
		const corrected = { ...submitted, page: data.page, per_page: data.per_page };
		queryClient.setQueryData(discoverySearchQuery(workspaceId, corrected).queryKey, data);
		void publish(corrected, true);
	});
	function addClause() {
		if (!providers.data || clauses.length >= providers.data.max_search_clauses) return;
		clauses.push({ id: nextClauseId++, field: 'any', operator: 'and', term: '' });
	}
	function removeClause(id: number) {
		clauses = clauses.filter((clause) => clause.id !== id);
	}
	function search() {
		if (!selectedProvider || busy) return;
		const body: SearchRequest = {
			provider,
			clauses: clauses.map(({ field, operator, term }) => ({ field, operator, term: term.trim() })),
			page: 1,
			per_page: results.data?.per_page ?? submitted?.per_page ?? 20,
			sort,
			year_from: yearFrom ? Number(yearFrom) : null,
			year_to: yearTo ? Number(yearTo) : null
		};
		if (!body.clauses.every((clause) => clause.term)) {
			validationError = $t`Enter a search term for each condition.`;
			return;
		}
		if (body.year_from && body.year_to && body.year_from > body.year_to) {
			validationError = $t`The starting year must not be after the ending year.`;
			return;
		}
		void loadResults(body);
	}
	async function loadResults(body: SearchRequest) {
		if (busy) return;
		const started = origin();
		const version = ++searchVersion;
		const previousAttempt = lastAttempt;
		validationError = '';
		navigationError = '';
		if (!reviewMutation.isPending) reviewMutation.reset();
		lastAttempt = body;
		try {
			if (previousAttempt)
				await queryClient.cancelQueries({
					queryKey: discoverySearchQuery(workspaceId, previousAttempt).queryKey,
					exact: true
				});
			if (version !== searchVersion || !isCurrent(started)) return;
			const data = await queryClient.fetchQuery({
				...discoverySearchQuery(workspaceId, body),
				staleTime: 0
			});
			if (version !== searchVersion || !isCurrent(started)) return;
			const actual = { ...body, page: data.page, per_page: data.per_page };
			queryClient.setQueryData(discoverySearchQuery(workspaceId, actual).queryKey, data);
			await publish(actual);
		} catch {
			// Query owns failures and retry state; the prior URL and results remain.
		}
	}
	async function review(candidates: Candidate[]) {
		if (!workspace.can('item.create') || reviewMutation.isPending || busy) return;
		const body = identifiersForCandidates(candidates);
		if (!body) return;
		reviewAttempt = [...candidates];
		const started = origin();
		const search = submitted;
		const writeBatch = await importBatchResponseWriter(queryClient, workspaceId);
		let batch: ImportBatch;
		try {
			batch = await reviewMutation.mutateAsync(body);
		} catch {
			// Mutation owns failure feedback, including its captured retry input.
			return;
		}
		if (
			!writeBatch(batch) &&
			queryClient.getQueryData(importKeys.batch(workspaceId, batch.id)) === null
		)
			return;
		void queryClient.invalidateQueries({ queryKey: importKeys.lists(workspaceId) });
		if (!isCurrent(started)) return;
		try {
			const parameters = new SvelteURLSearchParams(search ? discoverySearchParameters(search) : '');
			parameters.set('batch', batch.id);
			parameters.set('from', 'discovery');
			await goto(resolve(workspaceHref(workspaceId, `import?${parameters}`)));
		} catch (reason) {
			if (isCurrent(started))
				navigationError = apiErrorMessage(reason, $t`Unable to open Import preview. Try again.`);
		}
	}
</script>

<SectionHeader>
	<div>
		<p class="mb-1 text-sm font-medium text-primary-700-300">{$t`External metadata`}</p>
		<h1>{$t`Discovery`}</h1>
		<p class="text-surface-600-400">
			{$t`Search external sources and preview records before importing.`}
		</p>
	</div>
</SectionHeader>
{#if providers.isError || providers.fetchStatus === 'paused'}
	<QueryError
		message={apiErrorMessage(providers.error, $t`Unable to load Discovery providers.`)}
		busy={providers.isFetching}
		onRetry={() => void providers.refetch()}
	/>
{:else if providers.isPending}
	<LoadingState label={$t`Loading Discovery providers…`} />
{:else if providers.data.search.length === 0}
	<Notice>{$t`No Discovery providers are available.`}</Notice>
{/if}
<Panel
	as="form"
	class="grid grid-cols-1 gap-3"
	onsubmit={(event) => {
		event.preventDefault();
		search();
	}}
>
	<div
		class="grid grid-cols-1 gap-3 lg:grid-cols-[minmax(12rem,1fr)_minmax(10rem,0.7fr)_9rem_9rem]"
	>
		<label class="grid grid-cols-1 gap-1">
			<span class="text-sm font-semibold">{$t`Provider`}</span>
			<select class="select" bind:value={provider}>
				{#each providers.data?.search ?? [] as option (option.id)}
					<option value={option.id}>{option.name}</option>
				{/each}
			</select>
		</label>
		<label class="grid grid-cols-1 gap-1">
			<span class="text-sm font-semibold">{$t`Sort`}</span>
			<select class="select" bind:value={sort}>
				{#each selectedProvider?.sorts ?? [] as option (option)}
					<option value={option}>{sortLabels[option]}</option>
				{/each}
			</select>
		</label>
		<DateField precision="year" label={$t`From year`} min="1000-01-01" bind:value={yearFrom} />
		<DateField precision="year" label={$t`To year`} min="1000-01-01" bind:value={yearTo} />
	</div>

	<div class="grid grid-cols-1 gap-2" aria-label={$t`Search conditions`}>
		{#each clauses as clause, index (clause.id)}
			<div class="grid grid-cols-1 gap-2 md:grid-cols-[7rem_10rem_minmax(12rem,1fr)_auto]">
				<select class="select" bind:value={clause.operator} aria-label={$t`Boolean operator`}>
					<option value="and">{$t`AND`}</option>
					<option value="or">{$t`OR`}</option>
					<option value="not">{$t`NOT`}</option>
				</select>
				<select class="select" bind:value={clause.field} aria-label={$t`Search field`}>
					<option value="any">{$t`Any field`}</option>
					<option value="title">{$t`Title`}</option>
					<option value="author">{$t`Author`}</option>
					<option value="publication">{$t`Publication`}</option>
					<option value="abstract">{$t`Abstract`}</option>
				</select>
				<input
					class="input"
					bind:value={clause.term}
					maxlength="300"
					placeholder={index === 0 ? $t`Title, author, DOI, or topic` : $t`Another condition`}
					required
				/>
				<Button
					type="button"
					disabled={clauses.length === 1}
					onclick={() => removeClause(clause.id)}>{$t`Remove`}</Button
				>
			</div>
		{/each}
	</div>
	<div class="flex flex-wrap items-center gap-2">
		<Button
			type="button"
			disabled={!providers.data || clauses.length >= providers.data.max_search_clauses}
			onclick={addClause}>{$t`Add condition`}</Button
		>
		<span class="grow basis-64"></span>
		<Button variant="filled" disabled={busy || !selectedProvider}
			>{busy ? $t`Searching…` : $t`Search Discovery`}</Button
		>
	</div>
</Panel>

{#if validationError}<Notice variant="error" class="mt-4">{validationError}</Notice>{/if}
{#if navigationError}<Notice variant="error" class="mt-4">{navigationError}</Notice>{/if}
{#if attemptFailed}
	<QueryError
		message={apiErrorMessage(attempt.error, $t`Search failed`)}
		{busy}
		onRetry={() => lastAttempt && void loadResults(lastAttempt)}
	/>
{:else if unavailable}
	<QueryError
		message={apiErrorMessage(results.error, $t`Search failed`)}
		{busy}
		onRetry={() => submitted && void loadResults(submitted)}
	/>
{/if}
{#if reviewMutation.isError}
	<QueryError
		message={apiErrorMessage(reviewMutation.error, $t`Import preview failed`)}
		busy={reviewMutation.isPending}
		onRetry={() => void review(reviewAttempt)}
	/>
{/if}
<Panel class="mt-4" aria-busy={busy}>
	<SectionHeader>
		<div>
			<h2>{$t`Candidate Records`}</h2>
			{#if results.data}<p class="text-surface-600-400">
					{$plural({ count: results.data.total }, { one: '# result', other: '# results' })}
				</p>{/if}
		</div>
	</SectionHeader>
	{#if busy}<LoadingState label={$t`Searching…`} />{/if}
	{#if results.data}
		{#if results.data.results.length}
			<DiscoveryResults
				data={results.data}
				selectionScope={`${submitted ? discoverySearchParameters(submitted) : ''}:${results.dataUpdatedAt}`}
				canImport={workspace.can('item.create')}
				{busy}
				importing={reviewMutation.isPending}
				onReview={(candidates) => void review(candidates)}
			/>
		{:else}
			<EmptyState
				icon="search"
				title={$t`No candidates found`}
				detail={$t`Try different terms, fewer conditions, or another Provider.`}
			/>
		{/if}
		<Pagination
			page={results.data.page}
			{pageCount}
			pageSize={results.data.per_page}
			pageSizeOptions={pageSizes}
			total={results.data.total}
			{busy}
			label={$t`Discovery result pages`}
			onPage={(next) => submitted && void loadResults({ ...submitted, page: next })}
			onPageSize={(size) =>
				submitted && void loadResults({ ...submitted, page: 1, per_page: size })}
		/>
	{:else if !busy && !unavailable && !attemptFailed}
		<EmptyState
			icon="search"
			title={$t`Search results will appear here.`}
			detail={$t`Search an external Provider to find records for your Library.`}
		/>
	{/if}
</Panel>
