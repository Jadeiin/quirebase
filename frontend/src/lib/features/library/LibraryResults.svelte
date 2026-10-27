<script lang="ts">
	import EmptyState from '#lib/design/EmptyState.svelte';
	import Button from '#lib/design/Button.svelte';
	import Icon from '#lib/design/Icon.svelte';
	import Pagination from '#lib/design/Pagination.svelte';
	import Panel from '#lib/design/Panel.svelte';
	import QueryError from '#lib/design/QueryError.svelte';
	import type { LibrarySearch } from './queries';
	import {
		defaultSortDirection,
		librarySort,
		type libraryHref,
		type LibraryMetadataFilter,
		type LibrarySort,
		type LibrarySortDirection
	} from './filters.js';
	import LibraryTable from './LibraryTable.svelte';
	import type { LibraryPreviewNavigation } from './preview-navigation.js';
	import type { LibraryBulkAction } from './mutations.js';
	import type { WorkspacePath } from '#lib/workspaces/href.js';
	import { ph, t } from 'lingui-for-svelte/macro';

	let {
		data,
		workspaceId,
		listingIdentity,
		shortcutsEnabled,
		filterHref,
		isPending,
		isError,
		pageNumber,
		pageSize,
		sort,
		direction,
		busy,
		totalPages,
		selected,
		previewItemId,
		previewNavigation,
		itemHref,
		currentProject,
		actionsBusy,
		onItemAction,
		onSelectionChange,
		onPreview,
		onPreviewReady,
		onClosePreview,
		onPage,
		onPageSize,
		onSort,
		onRetry
	}: {
		data?: LibrarySearch | null;
		workspaceId: string;
		listingIdentity: string;
		shortcutsEnabled: boolean;
		filterHref: (filter: LibraryMetadataFilter | { tag: string }) => ReturnType<typeof libraryHref>;
		isPending: boolean;
		isError: boolean;
		pageNumber: number;
		pageSize: number;
		sort: LibrarySort;
		direction: LibrarySortDirection;
		busy: boolean;
		totalPages: number;
		selected: Set<string>;
		previewItemId: string;
		previewNavigation: LibraryPreviewNavigation;
		itemHref: (id: string, suffix?: string) => WorkspacePath;
		currentProject: { id: string; name: string } | null;
		actionsBusy: boolean;
		onItemAction: (action: LibraryBulkAction, id: string, trigger: HTMLElement) => void;
		onSelectionChange: (ids: string[]) => void;
		onPreview: (id: string, trigger: HTMLElement) => void;
		onPreviewReady: (heading: HTMLHeadingElement) => void;
		onClosePreview: () => void;
		onPage: (page: number) => void;
		onPageSize: (size: number) => void;
		onSort: (sort: LibrarySort, direction: LibrarySortDirection) => void;
		onRetry: () => void;
	} = $props();
	let previewLoadAttempt = $state(0);
	let sortFocus = $state<{
		sort: LibrarySort;
		direction: LibrarySortDirection;
		control: 'header' | 'field' | 'direction';
	} | null>(null);
	$effect(() => {
		if (!busy && sortFocus?.sort === sort && sortFocus.direction === direction) {
			if (document.activeElement === document.body) {
				document
					.getElementById(
						sortFocus.control === 'header'
							? `library-sort-${sort}`
							: `library-sort-${sortFocus.control}`
					)
					?.focus();
			}
			sortFocus = null;
		}
	});
	const sortOptions = $derived([
		{ value: 'updated', label: $t`Date modified` },
		{ value: 'created', label: $t`Date added` },
		{ value: 'published', label: $t`Publication date` },
		{ value: 'publication', label: $t`Publication` },
		{ value: 'author', label: $t`Author` },
		{ value: 'title', label: $t`Title` }
	] as const);
	function orderLabel(field: LibrarySort, order: LibrarySortDirection) {
		return field === 'title' || field === 'publication' || field === 'author'
			? order === 'asc'
				? $t`A–Z`
				: $t`Z–A`
			: order === 'asc'
				? $t`Oldest first`
				: $t`Newest first`;
	}
	const nextDirection = $derived(direction === 'asc' ? 'desc' : 'asc');
	const directionHint = $derived(
		$t`Sort order: ${ph({ current: orderLabel(sort, direction) })}. Switch to ${ph({ next: orderLabel(sort, nextDirection) })}.`
	);
</script>

{#snippet sortControls()}
	<div
		role="group"
		aria-label={$t`Sort`}
		class="field-group min-w-0 grid-cols-[minmax(0,1fr)_auto] gap-0"
	>
		<select
			id="library-sort-field"
			aria-label={$t`Sort By`}
			class="select h-9 w-auto max-w-full text-xs"
			value={sort}
			disabled={busy}
			onchange={(event) => {
				const nextSort = librarySort(event.currentTarget.value);
				const order = defaultSortDirection(nextSort);
				sortFocus = { sort: nextSort, direction: order, control: 'field' };
				onSort(nextSort, order);
			}}
		>
			{#each sortOptions as option (option.value)}
				<option value={option.value}>{option.label}</option>
			{/each}
		</select>
		<Button
			id="library-sort-direction"
			type="button"
			variant="icon"
			class="-ml-px size-9"
			aria-label={directionHint}
			title={directionHint}
			disabled={busy}
			onclick={() => {
				sortFocus = { sort, direction: nextDirection, control: 'direction' };
				onSort(sort, nextDirection);
			}}><Icon name={direction === 'asc' ? 'arrow-up' : 'arrow-down'} size={16} /></Button
		>
	</div>
{/snippet}

<div
	id="library-results"
	tabindex="-1"
	class="mt-6 grid min-w-0 grid-cols-1 items-start gap-4 focus:outline-none"
	class:xl:grid-cols-[minmax(0,1fr)_22rem]={Boolean(previewItemId)}
>
	<Panel padding="none" class="min-w-0">
		{#if isPending || !data?.items.length}
			<div
				class="flex flex-wrap items-center justify-end gap-2 border-b border-surface-300-700 px-4 py-3"
			>
				{@render sortControls()}
			</div>
		{/if}
		{#if isPending}<div
				class="grid min-h-56 grid-cols-1 place-items-center text-surface-600-400"
				role="status"
			>
				{$t`Loading Library…`}
			</div>
		{:else if !data}<div class="px-4">
				<QueryError message={$t`Unable to load the Library.`} {busy} {onRetry} />
			</div>
		{:else}
			{#if isError}<div class="px-4">
					<QueryError
						message={$t`Unable to refresh the Library. Showing the last loaded results.`}
						{busy}
						{onRetry}
					/>
				</div>{/if}
			{#if !data?.items.length}<EmptyState
					title={$t`No Items found.`}
					detail={$t`Try a different Library Search.`}
				/>
			{:else}<LibraryTable
					items={data.items}
					toolbar={sortControls}
					{listingIdentity}
					{shortcutsEnabled}
					{filterHref}
					{selected}
					{onSelectionChange}
					{onPreview}
					{previewItemId}
					{itemHref}
					{currentProject}
					{actionsBusy}
					{onItemAction}
					{sort}
					{direction}
					onSort={(sort, direction) => {
						sortFocus = { sort, direction, control: 'header' };
						onSort(sort, direction);
					}}
					{busy}
				/>{/if}
		{/if}
		<Pagination
			page={pageNumber}
			pageCount={totalPages}
			{pageSize}
			total={data?.total ?? 0}
			{busy}
			label={$t`Library pages`}
			{onPage}
			{onPageSize}
		/>
	</Panel>
	{#if previewItemId}
		{#key `${previewItemId}:${previewLoadAttempt}`}
			{#await import('./LibraryPreview.svelte')}
				<p role="status" class="p-4 text-sm text-surface-600-400">{$t`Loading Item preview…`}</p>
			{:then { default: LibraryPreview }}
				<LibraryPreview
					{workspaceId}
					itemId={previewItemId}
					navigation={previewNavigation}
					{shortcutsEnabled}
					{currentProject}
					{actionsBusy}
					onAction={(action, trigger) => onItemAction(action, previewItemId, trigger)}
					itemHref={(suffix) => itemHref(previewItemId, suffix)}
					{filterHref}
					onClose={onClosePreview}
					onReady={onPreviewReady}
				/>
			{:catch}<div>
					<QueryError
						message={$t`Unable to load this Item preview.`}
						onRetry={() => previewLoadAttempt++}
					/><Button onclick={onClosePreview}>{$t`Close preview`}</Button>
				</div>{/await}
		{/key}
	{/if}
</div>
