<script lang="ts">
	import { resolve } from '$app/paths';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { onDestroy, tick } from 'svelte';
	import { SvelteMap, SvelteSet, SvelteURLSearchParams } from 'svelte/reactivity';
	import { Tabs } from '@skeletonlabs/skeleton-svelte';
	import { apiErrorMessage } from '#lib/api/errors.js';
	import Badge from '#lib/design/Badge.svelte';
	import Button from '#lib/design/Button.svelte';
	import EmptyState from '#lib/design/EmptyState.svelte';
	import ItemRow from '#lib/design/ItemRow.svelte';
	import LoadingState from '#lib/design/LoadingState.svelte';
	import Notice from '#lib/design/Notice.svelte';
	import Pagination from '#lib/design/Pagination.svelte';
	import Panel from '#lib/design/Panel.svelte';
	import QueryError from '#lib/design/QueryError.svelte';
	import { domainLabel } from '#lib/domain-labels.js';
	import { dateTimeFormat } from '#lib/format.js';
	import { t } from '#lib/i18n.js';
	import { getWorkspaceContext } from '#lib/workspaces/context.svelte.js';
	import { workspaceHref } from '#lib/workspaces/href.js';
	import { importBatchesQuery } from './queries.js';
	import { deleteImportBatch } from './mutations.js';
	import { importListParameters, readImportListState, type ImportListState } from './list-state.js';

	const workspace = getWorkspaceContext();
	const { workspaceId } = workspace;
	const client = useQueryClient();
	const pending = new SvelteSet<string>();
	const errors = new SvelteMap<string, string>();
	let results: HTMLElement;
	let focusVersion = 0;
	let mounted = true;
	onDestroy(() => {
		mounted = false;
	});
	const listing = $derived(readImportListState(page.url.searchParams));
	const batches = createQuery(() =>
		importBatchesQuery(workspaceId, listing.view, listing.page, listing.pageSize)
	);
	const unavailable = $derived(batches.data === null || batches.fetchStatus === 'paused');
	const lastPage = $derived(Math.max(1, Math.ceil((batches.data?.total ?? 0) / listing.pageSize)));

	function navigate(next: ImportListState, replace = false) {
		// eslint-disable-next-line svelte/prefer-svelte-reactivity -- this local navigation target holds no reactive state
		const url = new URL(page.url.href);
		url.search = importListParameters(next, url.searchParams).toString();
		// eslint-disable-next-line svelte/no-navigation-without-resolve -- page.url is already resolved
		void goto(url, { reset: false, replace, state: page.state });
	}
	function batchHref(id: string) {
		const parameters = new SvelteURLSearchParams(page.url.search);
		parameters.set('from', 'history');
		parameters.set('batch', id);
		return workspaceHref(workspaceId, `import?${parameters}`);
	}
	async function remove(batch: { id: string; status: string }) {
		if (!workspace.can('item.create') || pending.has(batch.id)) return;
		const target = document.activeElement;
		const version = focusVersion;
		const startedUrl = page.url;
		const index = [...results.querySelectorAll('[data-import-batch]')].findIndex((row) =>
			row.contains(target)
		);
		pending.add(batch.id);
		errors.delete(batch.id);
		try {
			await deleteImportBatch(client, workspaceId, batch.id);
			await tick();
			if (
				mounted &&
				page.url === startedUrl &&
				focusVersion === version &&
				target instanceof HTMLElement &&
				!target.isConnected &&
				document.activeElement === document.body &&
				index >= 0
			) {
				const rows = results.querySelectorAll('[data-import-batch]');
				const adjacent =
					rows[Math.min(index, rows.length - 1)]?.querySelector<HTMLAnchorElement>('a');
				(adjacent ?? results).focus();
			}
		} catch (reason) {
			errors.set(
				batch.id,
				apiErrorMessage(
					reason,
					batch.status === 'committed'
						? $t('Unable to delete import record')
						: $t('Unable to discard Import')
				)
			);
		} finally {
			pending.delete(batch.id);
		}
	}
	$effect(() => {
		if (
			batches.isSuccess &&
			batches.fetchStatus === 'idle' &&
			batches.data &&
			listing.page > lastPage
		)
			navigate({ ...listing, page: lastPage }, true);
	});
</script>

<svelte:document
	onfocusin={(event) => {
		if (event.target !== document.body) focusVersion++;
	}}
/>

<section bind:this={results} tabindex="-1" aria-label={$t('Import history')}>
	<Panel class="mb-6">
		<Tabs
			value={listing.view}
			onValueChange={({ value }) => {
				navigate({ ...listing, view: value === 'completed' ? 'completed' : 'pending', page: 1 });
			}}
		>
			<div class="mb-3 flex flex-wrap items-center justify-between gap-3">
				<Tabs.List aria-label={$t('Import history')}>
					<Tabs.Indicator />
					<Tabs.Trigger value="pending">{$t('Pending imports')}</Tabs.Trigger>
					<Tabs.Trigger value="completed">{$t('Completed imports')}</Tabs.Trigger>
				</Tabs.List>
			</div>
			<Tabs.Content value={listing.view}>
				{#if batches.isError || unavailable}
					<QueryError
						message={apiErrorMessage(batches.error, $t('Unable to load imports'))}
						busy={batches.isFetching}
						onRetry={() => void batches.refetch()}
					/>
				{/if}
				{#if batches.isPending && !unavailable}
					<LoadingState label={$t('Loading imports…')} />
				{:else if batches.data && !unavailable}
					{#each batches.data.items as batch (batch.id)}
						<ItemRow data-import-batch={batch.id}>
							<div class="flex flex-wrap items-center justify-between gap-3">
								<div class="grid grid-cols-1 gap-1">
									<div class="flex flex-wrap items-center gap-2">
										<strong>{$dateTimeFormat.format(new Date(batch.created_at))}</strong>
										<Badge
											>{batch.status === 'committed'
												? $t('Imported')
												: $t(domainLabel(batch.status))}</Badge
										>
									</div>
									<span class="text-sm text-surface-600-400">
										{batch.file_format} · {$t('{count, plural, one {# record} other {# records}}', {
											count: batch.record_count
										})}
										{#if batch.diagnostic_count}
											· {$t('{count, plural, one {# issue} other {# issues}}', {
												count: batch.diagnostic_count
											})}{/if}
									</span>
								</div>
								<div class="flex flex-wrap items-center gap-2">
									<Button as="a" href={resolve(batchHref(batch.id))}>{$t('Open import')}</Button>
									{#if workspace.can('item.create')}
										<Button
											variant="danger"
											disabled={pending.has(batch.id)}
											onclick={() => void remove(batch)}
										>
											{batch.status === 'committed' ? $t('Delete import record') : $t('Discard')}
										</Button>
									{/if}
								</div>
							</div>
							{#if errors.has(batch.id)}<Notice variant="error" class="mt-2"
									>{errors.get(batch.id)}</Notice
								>{/if}
						</ItemRow>
					{:else}
						<EmptyState
							icon="import"
							title={listing.view === 'pending'
								? $t('No pending imports')
								: $t('No completed imports')}
						/>
					{/each}
					{#if batches.data.total > listing.pageSize || listing.page > 1}
						<Pagination
							page={listing.page}
							pageSize={listing.pageSize}
							pageCount={lastPage}
							total={batches.data.total}
							label={$t('Import pages')}
							busy={batches.isFetching}
							onPage={(next) => navigate({ ...listing, page: next })}
							onPageSize={(next) => navigate({ ...listing, pageSize: next, page: 1 })}
						/>
					{/if}
				{/if}
			</Tabs.Content>
		</Tabs>
	</Panel>
</section>
