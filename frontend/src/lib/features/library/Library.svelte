<script lang="ts">
	import Button from '#lib/design/Button.svelte';
	import { resolve } from '$app/paths';
	import { afterNavigate, beforeNavigate, goto } from '$app/navigation';
	import { onDestroy, tick, untrack } from 'svelte';
	import { page } from '$app/state';
	import {
		createMutation,
		createInfiniteQuery,
		createQuery,
		useQueryClient
	} from '@tanstack/svelte-query';
	import { SvelteSet } from 'svelte/reactivity';
	import { isDownloadCancelled } from '#lib/api/client.js';
	import { apiErrorMessage } from '#lib/api/errors.js';
	import ConfirmDialog from '#lib/design/ConfirmDialog.svelte';
	import StatusNotice from '#lib/design/StatusNotice.svelte';
	import BulkActions from '#lib/features/library/BulkActions.svelte';
	import LibraryFilters from '#lib/features/library/LibraryFilters.svelte';
	import LibraryResults from '#lib/features/library/LibraryResults.svelte';
	import LibraryShortcuts from './LibraryShortcuts.svelte';
	import {
		libraryBulkMutationOptions,
		type LibraryBulkAction,
		type LibraryBulkInput
	} from '#lib/features/library/mutations.js';
	import { libraryListQuery } from '#lib/features/library/queries.js';
	import {
		readLibraryFilters,
		libraryPage,
		libraryPageSize,
		libraryHref,
		libraryParameters,
		refineLibraryFilters,
		type LibraryFilters as AppliedLibraryFilters
	} from './filters.js';
	import LibraryActiveFilters from './LibraryActiveFilters.svelte';
	import { projectDetailQuery, projectOptionsQuery } from '#lib/features/projects/queries.js';
	import { getSession } from '#lib/session.js';
	import {
		defaultExportPreferences,
		readExportPreferences,
		type ExportPreferences
	} from '#lib/export-preferences.js';
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
	let bulkAction = $state('');
	let bulkProject = $state('');
	let bulkTag = $state('');
	let bulkTagId = $state('');
	let exportFormat = $state('bibtex');
	let error = $state('');
	let notice = $state('');
	let confirmBulkOpen = $state(false);
	let confirmedInput = $state<LibraryBulkInput | null>(null);
	let confirmedSelectionVersion = 0;
	let confirmationTrigger: HTMLElement | null = null;
	let confirmationProjectName = $state('');
	let exportPreferences = $state<ExportPreferences>(structuredClone(defaultExportPreferences));
	const queryClient = useQueryClient();
	const workspace = getWorkspaceContext();
	const { workspaceId } = workspace;
	const { query: session } = getSession();
	const bulkMutation = createMutation(() => libraryBulkMutationOptions(workspaceId, queryClient));
	const busy = $derived(bulkMutation.isPending);
	$effect(() => {
		if (!confirmBulkOpen && !busy) confirmedInput = null;
	});

	let previousSearch = '';
	$effect(() => {
		const search = listingIdentity;
		if (search === previousSearch) return;
		previousSearch = search;
		if (!busy) confirmBulkOpen = false;
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
	const projects = createInfiniteQuery(() => projectOptionsQuery(workspaceId));
	const selectedProject = createQuery(() => ({
		...projectDetailQuery(workspaceId, submitted.project ?? ''),
		enabled: Boolean(submitted.project) && !projects.data?.some((p) => p.id === submitted.project)
	}));
	const projectChoices = $derived(
		selectedProject.data && !projects.data?.some((p) => p.id === selectedProject.data?.id)
			? [selectedProject.data, ...(projects.data ?? [])]
			: (projects.data ?? [])
	);
	const currentProject = $derived(
		projectChoices.find(
			(candidate) =>
				candidate.id === submitted.project && can(candidate.authorization, 'project_item.manage')
		) ?? null
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
			confirmBulkOpen = false;
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

	$effect(() => {
		if (session.data?.user) {
			const loadedPreferences = readExportPreferences(session.data.user.id, workspaceId);
			exportPreferences = loadedPreferences;
			exportFormat = loadedPreferences.citation.format;
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
		navigate({
			...submitted,
			query: query.trim(),
			tag,
			project,
			year: year.trim(),
			keyword: keyword.trim(),
			author: author.trim(),
			has_files: fileFilter ? fileFilter === 'true' : undefined
		});
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

	function requestBulkAction() {
		if (!bulkAction || selected.size === 0 || bulkMutation.isPending) return;
		if (!canRunBulkAction(workspace.can, bulkAction as LibraryBulkAction)) return;
		if (bulkAction === 'remove_project' && !currentProject) return;
		if (bulkAction === 'delete' || bulkAction === 'remove_project') {
			confirmationTrigger =
				document.activeElement instanceof HTMLElement ? document.activeElement : null;
			confirmedInput = currentBulkInput();
			confirmedSelectionVersion = selectionVersion;
			confirmationProjectName = currentProject?.name ?? '';
			error = '';
			confirmBulkOpen = true;
			return;
		}
		void executeBulkAction();
	}

	function currentBulkInput(): LibraryBulkInput {
		return {
			action: bulkAction as LibraryBulkAction,
			itemIds: [...selected],
			projectId: bulkAction === 'remove_project' ? (currentProject?.id ?? '') : bulkProject,
			tagName: bulkTag,
			tagId: bulkTagId,
			exportFormat,
			preferences: $state.snapshot(exportPreferences)
		};
	}

	async function executeBulkAction() {
		if (busy) return;
		const input = confirmedInput ?? currentBulkInput();
		if (!input.action || input.itemIds.length === 0) return;
		if (!canRunBulkAction(workspace.can, input.action)) return;
		error = '';
		notice = '';
		const submittedSelectionVersion = confirmedInput ? confirmedSelectionVersion : selectionVersion;
		const trigger = document.activeElement instanceof HTMLElement ? document.activeElement : null;
		try {
			await bulkMutation.mutateAsync({
				input,
				afterMutation: () => {
					if (selectionVersion === submittedSelectionVersion) clearSelection(trigger);
				}
			});
			confirmBulkOpen = false;
			notice = $t('Bulk action completed');
		} catch (reason) {
			if (isDownloadCancelled(reason)) return;
			error = apiErrorMessage(reason, $t('Bulk action failed'));
		}
	}
</script>

<svelte:document onfocusin={() => focusVersion++} />

<div class="mb-8 flex items-end justify-between gap-4">
	<div>
		<p class="mb-2 text-xs font-bold tracking-[0.12em] text-primary-700-300 uppercase">
			{$t('Workspace')}
		</p>
		<h1 class="mb-2">{$t('Library')}</h1>
		<p class="m-0 max-w-2xl text-surface-700-300">
			{$t('Search, select, organize, and export your scholarly Items.')}
		</p>
	</div>
	<div class="flex shrink-0 items-center gap-2">
		{#if library.data}<span
				class="hidden rounded-full border border-surface-300-700 bg-surface-50-950 px-3 py-1.5 text-xs font-semibold text-surface-600-400 sm:inline"
				>{$t('{count, plural, one {# Item} other {# Items}}', {
					count: library.data.total
				})}</span
			>{/if}
		<LibraryShortcuts
			bind:enabled={shortcutsEnabled}
			onSearch={() => searchInput?.focus()}
			onEscape={escape}
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
	projects={projectChoices}
	onSearch={search}
	onClear={clearFilters}
/>

<LibraryActiveFilters filters={submitted} onRemove={removeFilters} />

<BulkActions
	bind:element={bulkActionsElement}
	selectedCount={selected.size}
	bind:bulkAction
	bind:bulkProject
	bind:bulkTag
	bind:bulkTagId
	{currentProject}
	bind:exportFormat
	projects={projectChoices}
	{busy}
	onApply={requestBulkAction}
	onClearSelection={() => clearSelection()}
/>

{#if projects.hasNextPage}<Button
		disabled={projects.isFetchingNextPage}
		onclick={() => void projects.fetchNextPage()}>{$t('Load more Projects')}</Button
	>{/if}

<ConfirmDialog
	bind:open={confirmBulkOpen}
	finalFocusEl={() =>
		confirmationTrigger?.isConnected
			? confirmationTrigger
			: document.getElementById('library-results')}
	title={confirmedInput?.action === 'remove_project'
		? $t('Remove the selected Items from {project}?', { project: confirmationProjectName })
		: $t('Permanently delete the selected Items?')}
	body={confirmedInput?.action === 'remove_project'
		? $t(
				'This permanently deletes their Annotations and Replies in this Project. Items, files, private Annotations, and other Projects are preserved.'
			)
		: $t('This cannot be undone.')}
	confirmLabel={confirmedInput?.action === 'remove_project'
		? $t('Remove from Project')
		: $t('Permanently delete')}
	{busy}
	error={confirmBulkOpen ? error : ''}
	onConfirm={() => void executeBulkAction()}
/>

<StatusNotice error={confirmBulkOpen ? '' : error} {notice} />

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
	onSelectionChange={setSelection}
	onPreview={preview}
	onPreviewReady={focusPreview}
	onClosePreview={() => preview('')}
	onPage={(next) => navigate(submitted, next)}
	onPageSize={(size) => navigate(submitted, 1, size)}
	onSort={(sort, direction) => navigate({ ...submitted, sort, direction })}
	onRetry={() => void library.refetch()}
/>
