<script lang="ts">
	import { resolve } from '$app/paths';
	import { afterNavigate, beforeNavigate, goto } from '$app/navigation';
	import { onDestroy, tick, untrack } from 'svelte';
	import { page } from '$app/state';
	import { createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { SvelteSet } from 'svelte/reactivity';
	import { apiErrorMessage } from '#lib/api/errors.js';
	import StatusNotice from '#lib/design/StatusNotice.svelte';
	import QueryError from '#lib/design/QueryError.svelte';
	import BulkActions from '#lib/features/library/BulkActions.svelte';
	import LibraryFilters from '#lib/features/library/LibraryFilters.svelte';
	import LibraryResults from '#lib/features/library/LibraryResults.svelte';
	import LibraryShortcuts from './LibraryShortcuts.svelte';
	import type { LibraryBulkAction } from './mutations.js';
	import LibraryActionDialog from './LibraryActionDialog.svelte';
	import type { LibraryActionRequest } from './action-request.js';
	import { libraryListQuery } from '#lib/features/library/queries.js';
	import {
		readLibraryFilters,
		libraryPage,
		libraryPageSize,
		libraryHref,
		libraryParameters,
		refineLibraryFilters,
		submitLibraryFilters,
		type LibraryFilters as AppliedLibraryFilters
	} from './filters.js';
	import LibraryActiveFilters from './LibraryActiveFilters.svelte';
	import LibrarySavedViews from './LibrarySavedViews.svelte';
	import { projectDetailQuery } from '#lib/features/projects/queries.js';
	import { getSession } from '#lib/session.js';
	import { t } from '#lib/i18n.js';
	import { getWorkspaceContext } from '#lib/workspaces/context.svelte.js';
	import { canRunBulkAction } from '#lib/workspaces/actions.js';
	import { can } from '#lib/authorization/can.js';
	import {
		libraryPreviewStep,
		reconcileLibraryPreviewPosition,
		type LibraryPreviewNavigation,
		type LibraryPreviewPosition
	} from './preview-navigation.js';
	import { libraryItemHref, libraryReturnItemId, libraryReturnTo } from './return-context.js';

	const submitted = $derived(readLibraryFilters(page.url.searchParams));
	const pageNumber = $derived(libraryPage(page.url.searchParams));
	const pageSize = $derived(libraryPageSize(page.url.searchParams));
	const previewItemId = $derived(page.url.searchParams.get('preview') ?? '');
	const listingIdentity = $derived(libraryParameters(submitted, pageNumber, pageSize).toString());
	let previewTrigger: HTMLElement | null = null;
	let previewFocusOrigin: Element | null = null;
	let previewReturnItemId = '';
	let focusVersion = 0;
	let returnFocus = $state<{ id: string; href: string; version: number } | null>(null);
	let previewRequest = 0;
	let mounted = true;
	let previewBusy = $state(false);
	let previewError = $state('');
	let previewRetryDirection: -1 | 1 = 1;
	let previewPosition = $state<(LibraryPreviewPosition & { listing: string }) | null>(null);
	beforeNavigate(() => {
		previewRequest++;
		previewBusy = false;
		previewError = '';
	});
	afterNavigate(() => {
		const id = libraryReturnItemId(page.url.hash);
		returnFocus = id ? { id, href: page.url.href, version: focusVersion } : null;
	});
	onDestroy(() => {
		mounted = false;
		previewRequest++;
	});
	let wasPreviewOpen = false;
	$effect(() => {
		const isPreviewOpen = Boolean(previewItemId);
		if (wasPreviewOpen && !isPreviewOpen) {
			const target = previewReturnItemId
				? document.getElementById(`library-item-${previewReturnItemId}`)
				: previewTrigger;
			if (target?.isConnected) target.focus();
			else document.getElementById('library-results')?.focus();
			previewTrigger = null;
			previewFocusOrigin = null;
			previewReturnItemId = '';
		}
		wasPreviewOpen = isPreviewOpen;
	});
	let query = $state(page.url.searchParams.get('q') ?? '');
	let tag = $state(page.url.searchParams.get('tag') ?? '');
	let project = $state(page.url.searchParams.get('project') ?? '');
	let year = $state(page.url.searchParams.get('year') ?? '');
	let keyword = $state(page.url.searchParams.get('keyword') ?? '');
	let author = $state(page.url.searchParams.get('author') ?? '');
	let fileFilter = $state(page.url.searchParams.get('has_files') ?? '');
	let filtersOpen = $state(false);
	let shortcutsEnabled = $state(true);
	let searchInput = $state<HTMLInputElement>();
	let selected = new SvelteSet<string>();
	let bulkActionsElement = $state<HTMLElement>();
	let selectionVersion = 0;
	let notice = $state('');
	let actionRequest = $state<LibraryActionRequest | null>(null);
	let busy = $state(false);
	const queryClient = useQueryClient();
	const workspace = getWorkspaceContext();
	const { workspaceId } = workspace;
	const { query: session } = getSession();

	let previousSearch = '';
	$effect(() => {
		const search = listingIdentity;
		if (search === previousSearch) return;
		previousSearch = search;
		clearSelection();
	});
	let previousFilters = '';
	$effect(() => {
		const search = libraryParameters({
			...submitted,
			sort: undefined,
			direction: undefined
		}).toString();
		if (search === previousFilters) return;
		previousFilters = search;
		query = page.url.searchParams.get('q') ?? '';
		tag = page.url.searchParams.get('tag') ?? '';
		project = page.url.searchParams.get('project') ?? '';
		year = page.url.searchParams.get('year') ?? '';
		keyword = page.url.searchParams.get('keyword') ?? '';
		author = page.url.searchParams.get('author') ?? '';
		fileFilter = page.url.searchParams.get('has_files') ?? '';
	});

	const library = createQuery(() => libraryListQuery(workspaceId, submitted, pageNumber, pageSize));
	const selectedProject = createQuery(() => ({
		...projectDetailQuery(workspaceId, submitted.project ?? ''),
		enabled: Boolean(submitted.project)
	}));
	const appliedProject = $derived(
		library.data && selectedProject.isSuccess && selectedProject.data?.id === submitted.project
			? selectedProject.data
			: null
	);
	const currentProject = $derived(
		appliedProject && can(appliedProject.authorization, 'project_item.manage')
			? appliedProject
			: null
	);
	const previewIndex = $derived(
		library.data?.items.findIndex((item) => item.id === previewItemId) ?? -1
	);
	$effect(() => {
		const data = library.data;
		const itemId = previewItemId;
		const listing = listingIdentity;
		if (!itemId || data === null) {
			previewPosition = null;
			return;
		}
		if (!data) return;
		const settled = library.isSuccess && library.fetchStatus === 'idle';
		untrack(() => {
			const previous = previewPosition?.listing === listing ? previewPosition : undefined;
			// A cached target page can be shorter than the authoritative page-clamp position.
			if (!settled && previous?.itemId === itemId && !previous.itemIds.length) return;
			const position = reconcileLibraryPreviewPosition(data.items, itemId, previous);
			previewPosition = position ? { ...position, listing } : null;
		});
	});
	const rememberedPreviewIndex = $derived(
		previewPosition?.listing === listingIdentity && previewPosition.itemId === previewItemId
			? previewPosition.index
			: undefined
	);
	function previewStep(direction: -1 | 1) {
		return (
			library.data &&
			libraryPreviewStep(
				{ ...library.data, page: pageNumber, pageSize },
				previewItemId,
				direction,
				rememberedPreviewIndex
			)
		);
	}
	const previewNavigation: LibraryPreviewNavigation = $derived({
		position: previewIndex < 0 ? null : (pageNumber - 1) * pageSize + previewIndex + 1,
		total: library.data?.total ?? 0,
		canPrevious: Boolean(previewStep(-1)),
		canNext: Boolean(previewStep(1)),
		busy: previewBusy || library.isFetching,
		error: previewError,
		previous: () => void movePreview(-1),
		next: () => void movePreview(1),
		retry: () => void movePreview(previewRetryDirection)
	});
	$effect(() => {
		const target = returnFocus;
		if (!target || library.isPending || library.isFetching) return;
		void tick().then(() => {
			if (returnFocus !== target || page.url.href !== target.href) return;
			returnFocus = null;
			if (focusVersion !== target.version) return;
			const element =
				document.getElementById(`library-item-${target.id}`) ??
				document.getElementById('library-results');
			element?.focus({ preventScroll: true });
			element?.scrollIntoView({ block: 'nearest' });
		});
	});
	const totalPages = $derived(Math.max(1, Math.ceil((library.data?.total ?? 0) / pageSize)));
	$effect(() => {
		if (library.isSuccess && library.data && !library.isFetching && pageNumber > totalPages) {
			const total = library.data.total;
			untrack(() => {
				if (previewItemId && previewIndex < 0 && rememberedPreviewIndex !== undefined) {
					// Removing the final result can remove its whole page. Keep its insertion
					// position at the end of the preceding page for continuous backward browsing.
					previewPosition = {
						listing: libraryParameters(submitted, totalPages, pageSize).toString(),
						itemId: previewItemId,
						index: Math.max(0, total - (totalPages - 1) * pageSize),
						itemIds: []
					};
				}
			});
			void goto(resolve(libraryHref(workspaceId, submitted, totalPages, pageSize, previewItemId)), {
				reset: false,
				replaceState: true
			});
		}
	});
	$effect(() => {
		if (library.data === null) {
			clearSelection();
			if (!busy) actionRequest = null;
			return;
		}
		if (!library.isSuccess || library.isFetching) return;
		const available = new Set(library.data.items.map((item) => item.id));
		// Refetches can remove rows. Do not retain invisible bulk targets.
		if (selected.size && ![...selected].some((id) => available.has(id))) {
			clearSelection();
			return;
		}
		for (const id of selected)
			if (!available.has(id)) {
				selectionVersion++;
				selected.delete(id);
			}
	});

	function navigate(filters: AppliedLibraryFilters, nextPage = 1, nextPageSize = pageSize) {
		clearSelection();
		void goto(resolve(libraryHref(workspaceId, filters, nextPage, nextPageSize, previewItemId)), {
			reset: false
		});
	}

	function preview(id: string, trigger?: HTMLElement) {
		if (trigger) {
			previewTrigger = trigger;
			previewFocusOrigin = trigger;
			previewReturnItemId = '';
		}
		void goto(resolve(libraryHref(workspaceId, submitted, pageNumber, pageSize, id)), {
			reset: false
		});
	}

	function focusPreview(heading: HTMLHeadingElement) {
		if (libraryReturnItemId(page.url.hash)) return;
		const focused = document.activeElement;
		const origin = previewFocusOrigin ?? document.getElementById('library-results');
		if (
			focused === origin ||
			(focused === document.body &&
				(!previewFocusOrigin ||
					!previewFocusOrigin.isConnected ||
					(previewFocusOrigin instanceof HTMLButtonElement && previewFocusOrigin.disabled)))
		)
			heading.focus();
	}

	async function movePreview(direction: -1 | 1) {
		if (previewBusy || library.isFetching) return;
		const step = previewStep(direction);
		if (!step) return;
		const request = ++previewRequest;
		const originUrl = page.url;
		const originFocus = document.activeElement;
		previewRetryDirection = direction;
		previewError = '';
		try {
			let id: string;
			if ('itemId' in step) id = step.itemId;
			else {
				previewBusy = true;
				const adjacent = await queryClient.fetchQuery({
					...libraryListQuery(workspaceId, submitted, step.page, pageSize),
					// An explicit navigation must settle with retry feedback even while offline.
					networkMode: 'always',
					retry: false
				});
				if (!mounted || request !== previewRequest || page.url !== originUrl) return;
				const item = step.edge === 'first' ? adjacent?.items[0] : adjacent?.items.at(-1);
				if (!item) throw new Error('Unavailable adjacent Library page');
				id = item.id;
			}
			previewFocusOrigin = originFocus;
			previewReturnItemId = id;
			await goto(resolve(libraryHref(workspaceId, submitted, step.page, pageSize, id)), {
				reset: false
			});
		} catch (reason) {
			if (mounted && request === previewRequest && page.url === originUrl) {
				previewError = apiErrorMessage(reason, $t('Unable to load the adjacent Library page.'));
			}
		} finally {
			if (mounted && request === previewRequest) previewBusy = false;
		}
	}

	function itemHref(id: string, suffix = '') {
		return libraryItemHref(
			workspaceId,
			id,
			suffix,
			libraryReturnTo(workspaceId, new URL(page.url.href), id)
		);
	}

	function search() {
		navigate(
			submitLibraryFilters(submitted, {
				query: query.trim(),
				tag,
				project,
				year: year.trim(),
				keyword: keyword.trim(),
				author: author.trim(),
				has_files: fileFilter ? fileFilter === 'true' : undefined
			})
		);
	}

	function removeFilters(keys: (keyof AppliedLibraryFilters)[]) {
		const next = { ...submitted };
		for (const key of keys) delete next[key];
		navigate(next);
	}

	function clearFilters() {
		query = tag = project = year = keyword = author = fileFilter = '';
		navigate({ sort: submitted.sort, direction: submitted.direction });
	}

	function setSelection(ids: string[]) {
		selectionVersion++;
		const available = new Set(library.data?.items.map((item) => item.id));
		selected.clear();
		for (const id of ids) if (available.has(id)) selected.add(id);
	}

	function clearSelection(origin: HTMLElement | null = null) {
		const focused = document.activeElement;
		const focusWillDisappear =
			bulkActionsElement?.isConnected &&
			(bulkActionsElement.contains(focused) ||
				(focused === document.body && bulkActionsElement.contains(origin)));
		selectionVersion++;
		selected.clear();
		if (focusWillDisappear) document.getElementById('library-results')?.focus();
	}

	function escape() {
		if (previewItemId) {
			preview('');
			return true;
		}
		if (!selected.size) return false;
		clearSelection();
		return true;
	}

	function requestAction(action: LibraryBulkAction, trigger: HTMLElement, itemId?: string) {
		if (busy || !canRunBulkAction(workspace.can, action)) return;
		if (action === 'remove_project' && !currentProject) return;
		const itemIds = itemId
			? [itemId]
			: (library.data?.items.filter((item) => selected.has(item.id)).map((item) => item.id) ?? []);
		if (!itemIds.length) return;
		const version = selectionVersion;
		const listing = listingIdentity;
		notice = '';
		actionRequest = {
			action,
			itemIds,
			source: itemId ? 'item' : 'selection',
			trigger,
			listing,
			project: currentProject ? { id: currentProject.id, name: currentProject.name } : null,
			afterMutation: itemId
				? undefined
				: () => {
						if (selectionVersion === version && listingIdentity === listing)
							clearSelection(trigger);
					}
		};
	}

	function copyCitation() {
		const focused = document.activeElement;
		if (!(focused instanceof HTMLElement)) return false;
		if (focused.closest('#library-preview') && previewItemId) {
			requestAction('copy_bibliography', focused, previewItemId);
		} else {
			const rowId = focused.closest<HTMLElement>('[data-library-item]')?.dataset.libraryItem;
			if (rowId && !selected.has(rowId)) requestAction('copy_bibliography', focused, rowId);
			else if (
				selected.size &&
				(focused.closest('#library-results') || bulkActionsElement?.contains(focused))
			)
				requestAction('copy_bibliography', focused);
			else return false;
		}
		return !busy && canRunBulkAction(workspace.can, 'copy_bibliography');
	}
</script>

<svelte:document onfocusin={() => focusVersion++} />

<div
	class="mb-8 flex flex-col items-start gap-4 sm:flex-row sm:flex-wrap sm:items-end sm:justify-between"
>
	<div>
		<p class="mb-2 text-xs font-bold tracking-[0.12em] text-primary-700-300 uppercase">
			{$t('Workspace')}
		</p>
		<h1 class="mb-2">{$t('Library')}</h1>
		<p class="m-0 max-w-2xl text-surface-700-300">
			{#if submitted.import_batch}
				{$t('Review this import, then select Items to add Tags or Projects.')}
			{:else}
				{$t('Search, select, organize, and export your scholarly Items.')}
			{/if}
		</p>
	</div>
	<div class="flex shrink-0 items-center gap-2">
		{#if library.data}<span
				class="hidden rounded-full border border-surface-300-700 bg-surface-50-950 px-3 py-1.5 text-xs font-semibold text-surface-600-400 sm:inline"
				>{$t('{count, plural, one {# Item} other {# Items}}', {
					count: library.data.total
				})}</span
			>{/if}
		<LibrarySavedViews filters={submitted} {pageSize} />
		<LibraryShortcuts
			bind:enabled={shortcutsEnabled}
			onSearch={() => searchInput?.focus()}
			onEscape={escape}
			onCopy={copyCitation}
		/>
	</div>
</div>

<LibraryFilters
	bind:searchInput
	{shortcutsEnabled}
	bind:query
	bind:tag
	bind:project
	bind:year
	bind:keyword
	bind:author
	bind:fileFilter
	bind:filtersOpen
	applied={submitted}
	{pageNumber}
	{pageSize}
	filterHref={(filter) =>
		libraryHref(workspaceId, refineLibraryFilters(submitted, filter), 1, pageSize, previewItemId)}
	onSearch={search}
	onClear={clearFilters}
/>

<LibraryActiveFilters
	filters={submitted}
	authors={library.data?.items.flatMap((item) => item.authors) ?? []}
	project={appliedProject}
	onRemove={removeFilters}
/>

{#if submitted.project && (selectedProject.isError || selectedProject.fetchStatus === 'paused')}
	<QueryError
		message={$t('Unable to load Project.')}
		busy={selectedProject.isFetching}
		onRetry={() => void selectedProject.refetch()}
	/>
{/if}

<BulkActions
	bind:element={bulkActionsElement}
	selectedCount={selected.size}
	{currentProject}
	{busy}
	onAction={(action, trigger) => requestAction(action, trigger)}
	onClearSelection={() => clearSelection()}
/>

<LibraryActionDialog
	bind:request={actionRequest}
	bind:busy
	userId={session.data?.user?.id ?? ''}
	{listingIdentity}
	onNotice={(message) => (notice = message)}
/>

<StatusNotice {notice} />

<LibraryResults
	{workspaceId}
	{listingIdentity}
	{shortcutsEnabled}
	filterHref={(filter) =>
		libraryHref(workspaceId, refineLibraryFilters(submitted, filter), 1, pageSize, previewItemId)}
	data={library.data}
	isPending={library.isPending || (!library.data && library.isFetching)}
	isError={library.isError ?? false}
	{pageNumber}
	{pageSize}
	sort={submitted.sort ?? 'updated'}
	direction={submitted.direction ?? 'desc'}
	busy={library.isFetching}
	{totalPages}
	{selected}
	{previewItemId}
	{previewNavigation}
	{itemHref}
	{currentProject}
	actionsBusy={busy}
	onItemAction={(action, itemId, trigger) => requestAction(action, trigger, itemId)}
	onSelectionChange={setSelection}
	onPreview={preview}
	onPreviewReady={focusPreview}
	onClosePreview={() => preview('')}
	onPage={(next) => navigate(submitted, next)}
	onPageSize={(size) => navigate(submitted, 1, size)}
	onSort={(sort, direction) => navigate({ ...submitted, sort, direction })}
	onRetry={() => void library.refetch()}
/>
