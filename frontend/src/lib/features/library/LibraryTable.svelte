<script lang="ts">
	import { resolve } from '$app/paths';
	import type { Snippet } from 'svelte';
	import { MediaQuery } from 'svelte/reactivity';
	import { Popover, Portal, SegmentedControl } from '@skeletonlabs/skeleton-svelte';
	import { createHotkeysAttachment } from '@tanstack/svelte-hotkeys';
	import {
		createTable,
		tableFeatures,
		columnVisibilityFeature,
		columnSizingFeature,
		columnResizingFeature,
		rowSelectionFeature,
		functionalUpdate,
		type RowSelectionState
	} from '@tanstack/svelte-table';
	import Button from '#lib/design/Button.svelte';
	import Icon from '#lib/design/Icon.svelte';
	import PopoverTriggerButton from '#lib/design/PopoverTriggerButton.svelte';
	import RichText from '#lib/design/RichText.svelte';
	import { getSession } from '#lib/session.js';
	import { t } from '#lib/i18n.js';
	import type { WorkspacePath } from '#lib/workspaces/href.js';
	import type { LibrarySearch } from './queries';
	import { libraryRowCommands, runLibraryShortcut, type LibraryRowCommand } from './shortcuts.js';
	import LibraryActionMenu from './LibraryActionMenu.svelte';
	import LibraryAuthors from './LibraryAuthors.svelte';
	import type { LibraryBulkAction } from './mutations.js';
	import {
		defaultSortDirection,
		type libraryHref,
		type LibraryMetadataFilter,
		type LibrarySort,
		type LibrarySortDirection
	} from './filters.js';
	import {
		defaultLibraryTablePreferences,
		readLibraryTablePreferences,
		writeLibraryTablePreferences,
		type LibraryTablePreferences
	} from './table-preferences';

	let {
		items,
		toolbar,
		listingIdentity,
		shortcutsEnabled,
		filterHref,
		selected,
		onSelectionChange,
		onPreview,
		previewItemId,
		itemHref,
		currentProject,
		actionsBusy,
		onItemAction,
		sort,
		direction,
		onSort,
		busy
	}: {
		items: LibrarySearch['items'];
		toolbar: Snippet;
		listingIdentity: string;
		shortcutsEnabled: boolean;
		filterHref: (filter: LibraryMetadataFilter) => ReturnType<typeof libraryHref>;
		selected: Set<string>;
		onSelectionChange: (ids: string[]) => void;
		onPreview: (id: string, trigger: HTMLElement) => void;
		previewItemId: string;
		itemHref: (id: string, suffix?: string) => WorkspacePath;
		currentProject: { id: string; name: string } | null;
		actionsBusy: boolean;
		onItemAction: (action: LibraryBulkAction, id: string, trigger: HTMLElement) => void;
		sort: LibrarySort;
		direction: LibrarySortDirection;
		onSort: (sort: LibrarySort, direction: LibrarySortDirection) => void;
		busy: boolean;
	} = $props();

	const session = getSession().query;
	const wide = new MediaQuery('(min-width: 1024px)');
	let preferences = $derived(readLibraryTablePreferences(session.data?.user?.id ?? ''));
	const showTable = $derived(
		preferences.view === 'table' || (preferences.view === 'auto' && wide.current)
	);
	function save(next: LibraryTablePreferences) {
		preferences = next;
		writeLibraryTablePreferences(session.data?.user?.id ?? '', next);
	}
	const rowSelection: RowSelectionState = $derived(
		Object.fromEntries([...selected].map((id) => [id, true as const]))
	);
	const columns = $derived([
		{
			id: 'select',
			header: $t('Select'),
			size: 48,
			minSize: 48,
			maxSize: 48,
			enableHiding: false,
			enableResizing: false
		},
		{
			accessorKey: 'title_html',
			header: $t('Title'),
			size: 360,
			minSize: 240,
			maxSize: 800,
			enableHiding: false
		},
		{ accessorKey: 'authors', header: $t('Authors'), size: 180, minSize: 100, maxSize: 800 },
		{
			accessorKey: 'publication_date',
			header: $t('Publication Date'),
			size: 140,
			minSize: 100,
			maxSize: 800
		},
		{
			accessorKey: 'publication_title',
			header: $t('Publication'),
			size: 190,
			minSize: 100,
			maxSize: 800
		},
		{ accessorKey: 'doi', header: $t('DOI'), size: 190, minSize: 100, maxSize: 800 },
		{
			id: 'preview',
			header: $t('Actions'),
			size: 104,
			minSize: 104,
			maxSize: 104,
			enableHiding: false,
			enableResizing: false
		}
	]);
	// Only the loaded server page enters the model. Query and the URL own filtering, sorting and paging.
	const table = createTable({
		features: tableFeatures({
			columnVisibilityFeature,
			columnSizingFeature,
			columnResizingFeature,
			rowSelectionFeature
		}),
		get data() {
			return items;
		},
		get columns() {
			return columns;
		},
		getRowId: (item) => item.id,
		// Pointer and keyboard ranges share the fixed anchor below; Table owns selection state.
		enableRowRangeSelection: false,
		columnResizeMode: 'onChange',
		state: {
			get rowSelection() {
				return rowSelection;
			},
			get columnVisibility() {
				return preferences.visibility;
			},
			get columnSizing() {
				return preferences.widths;
			}
		},
		onRowSelectionChange: (update) =>
			onSelectionChange(Object.keys(functionalUpdate(update, rowSelection))),
		onColumnVisibilityChange: (update) =>
			save({ ...preferences, visibility: functionalUpdate(update, preferences.visibility) }),
		onColumnSizingChange: (update) => {
			const sizes = functionalUpdate(update, preferences.widths);
			// TanStack clamps displayed sizes, but its updater can contain out-of-bounds drag values.
			const widths = Object.fromEntries(
				table
					.getAllLeafColumns()
					.filter((column) => column.getCanResize() && sizes[column.id] !== undefined)
					.map((column) => [
						column.id,
						Math.max(
							column.columnDef.minSize ?? 100,
							Math.min(column.columnDef.maxSize ?? 800, sizes[column.id])
						)
					])
			);
			save({ ...preferences, widths });
		}
	});
	let rangeStart: string | undefined;
	let rangeEnd: string | undefined;
	const rangeScope = $derived(`${listingIdentity}:${items.map((item) => item.id).join(',')}`);
	let previousRangeScope = '';
	$effect(() => {
		const count = selected.size;
		if (rangeScope !== previousRangeScope || count === 0) resetRange();
		previousRangeScope = rangeScope;
	});
	function resetRange() {
		rangeStart = undefined;
		rangeEnd = undefined;
	}
	function toggleItem(id: string, checked?: boolean) {
		rangeStart = rangeEnd = id;
		table.getRow(id).toggleSelected(checked);
	}
	function extendRange(endpoint: string, origin?: string) {
		const ids = table.getRowModel().rows.map((row) => row.id);
		if (!rangeStart || !ids.includes(rangeStart) || (origin && rangeEnd !== origin))
			rangeStart = origin ?? endpoint;
		const anchor = ids.indexOf(rangeStart);
		const end = ids.indexOf(endpoint);
		table.setRowSelection(
			Object.fromEntries(
				ids.slice(Math.min(anchor, end), Math.max(anchor, end) + 1).map((id) => [id, true])
			)
		);
		rangeEnd = endpoint;
	}
	function selectWithPointer(id: string, event: MouseEvent) {
		const checkbox = event.currentTarget as HTMLInputElement;
		if (!event.shiftKey) {
			toggleItem(id, checkbox.checked);
			return;
		}
		extendRange(id);
		// A checked endpoint may be clicked again while shrinking the same range.
		checkbox.checked = true;
	}
	function selectPage(checked = true) {
		resetRange();
		table.toggleAllRowsSelected(checked);
	}
	const rowHotkeys = createHotkeysAttachment(
		() =>
			libraryRowCommands.flatMap((command) =>
				command.keys.map((binding) => ({
					hotkey: binding.hotkey,
					callback: (event: KeyboardEvent) =>
						runLibraryShortcut(event, () => runRowCommand(command.id, event), command.repeat),
					options: { enabled: !busy && (!binding.character || shortcutsEnabled) }
				}))
			),
		{ preventDefault: false, stopPropagation: false, ignoreInputs: false, requireReset: false }
	);
	function runRowCommand(command: LibraryRowCommand, event: KeyboardEvent) {
		const region = event.currentTarget;
		const target = event.target;
		if (!(region instanceof HTMLElement) || !(target instanceof HTMLElement)) return false;
		const controls = [...region.querySelectorAll<HTMLInputElement>('[data-library-item-select]')];
		const current = controls.findIndex((control) =>
			control.closest('[data-library-item]')?.contains(target)
		);
		if (!controls.length || (current < 0 && target !== region)) return false;
		if (command === 'all') {
			selectPage();
			return true;
		}
		const id = controls[current]?.dataset.libraryItemSelect;
		if (command === 'actions') {
			const menu = controls[current]
				?.closest('[data-library-item]')
				?.querySelector<HTMLButtonElement>('[data-library-item-actions]');
			if (!menu || menu.disabled) return false;
			menu.focus();
			menu.click();
			return true;
		}
		if (command === 'toggle' || command === 'only' || command === 'preview') {
			if (!id) return false;
			if (command === 'toggle') toggleItem(id);
			else if (command === 'only') {
				rangeStart = rangeEnd = id;
				table.setRowSelection({ [id]: true });
			} else {
				// Links and buttons keep their native Enter action.
				if (event.key === 'Enter' && target !== controls[current]) return false;
				onPreview(id, target);
			}
			return true;
		}
		const last = controls.length - 1;
		const backwards = command === 'previous' || command === 'extendUp';
		const next =
			command === 'first'
				? 0
				: command === 'last'
					? last
					: current < 0
						? backwards
							? last
							: 0
						: Math.max(0, Math.min(last, current + (backwards ? -1 : 1)));
		if (command === 'extendUp' || command === 'extendDown') {
			extendRange(controls[next].dataset.libraryItemSelect!, id);
		} else rangeStart = rangeEnd = controls[next].dataset.libraryItemSelect;
		const control = controls[next];
		control.focus({ preventScroll: true });
		control.scrollIntoView({ block: 'nearest', inline: 'nearest' });
		// Sticky headers and mobile navigation can cover a natively scrolled focus target.
		const bounds = control.getBoundingClientRect();
		if (
			document.elementFromPoint(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2) !==
			control
		)
			control.scrollIntoView({ block: 'center', inline: 'nearest' });
		return true;
	}

	function resizeWithKeyboard(event: KeyboardEvent, id: string) {
		if (event.isComposing || !['ArrowLeft', 'ArrowRight', 'Home'].includes(event.key)) return;
		event.preventDefault();
		const column = table.getColumn(id);
		if (!column) return;
		if (event.key === 'Home') {
			column.resetSize();
			return;
		}
		const size = column.getSize() + (event.key === 'ArrowRight' ? 20 : -20);
		table.setColumnSizing((previous) => ({
			...previous,
			[id]: size
		}));
	}

	function selectionLabel(authors: LibrarySearch['items'][number]['authors']) {
		if (!authors.length) return $t('Select');
		const names = authors
			.slice(0, 3)
			.map((author) => author.full_name)
			.join('; ');
		return $t('Select {name}', {
			name: authors.length > 3 ? $t('{names} et al.', { names }) : names
		});
	}
</script>

{#snippet authorLinks(item: LibrarySearch['items'][number])}
	<LibraryAuthors
		authors={item.authors}
		{filterHref}
		previewOpen={previewItemId === item.id}
		onShowAll={(trigger) => onPreview(item.id, trigger)}
	/>
{/snippet}

{#snippet publicationLink(publication: string | null)}
	{#if publication}<a
			class="text-surface-700-300 no-underline underline-offset-4 hover:text-primary-700-300 hover:underline focus-visible:underline"
			href={resolve(filterHref({ publication_title: publication }))}
			title={$t('View Items in {name}', { name: publication })}
			aria-label={$t('View Items in {name}', { name: publication })}>{publication}</a
		>{:else}—{/if}
{/snippet}

{#snippet dateLink(date: string | null)}
	{#if date && /^\d{4}(?:-|$)/.test(date)}
		{@const year = date.slice(0, 4)}
		<a
			class="text-surface-700-300 no-underline underline-offset-4 hover:text-primary-700-300 hover:underline focus-visible:underline"
			href={resolve(filterHref({ year }))}
			title={$t('View Items published in {year}', { year })}
			aria-label={$t('View Items published in {year}', { year })}>{year}</a
		>{date.slice(4)}
	{:else}{date || '—'}{/if}
{/snippet}

<div
	class="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-surface-300-700 px-4 py-3"
	role="group"
	aria-label={$t('Library controls')}
>
	<label class="flex items-center gap-2 text-sm font-medium">
		<input
			type="checkbox"
			checked={table.getIsAllRowsSelected()}
			indeterminate={table.getIsSomeRowsSelected() && !table.getIsAllRowsSelected()}
			onchange={(event) => selectPage(event.currentTarget.checked)}
		/>
		{$t('Select this page')}
	</label>
	<div class="ml-auto flex max-w-full flex-wrap items-center gap-3">
		{@render toolbar()}
		<SegmentedControl
			value={preferences.view}
			onValueChange={({ value }) =>
				save({ ...preferences, view: value === 'table' || value === 'list' ? value : 'auto' })}
		>
			<SegmentedControl.Label class="sr-only">{$t('View')}</SegmentedControl.Label>
			<SegmentedControl.Control class="gap-0 p-0.5">
				<SegmentedControl.Indicator />
				{#each [{ value: 'auto', icon: 'responsive', label: $t('Automatic'), hint: $t('Automatic: Table on wide screens, List on narrow screens') }, { value: 'table', icon: 'table', label: $t('Table'), hint: $t('Table') }, { value: 'list', icon: 'list', label: $t('List'), hint: $t('List') }] as option (option.value)}
					<SegmentedControl.Item value={option.value} title={option.hint} class="px-2.5 py-2">
						<SegmentedControl.ItemText>
							<Icon name={option.icon} size={16} />
							<span class="sr-only">{option.label}</span>
						</SegmentedControl.ItemText>
						<SegmentedControl.ItemHiddenInput />
					</SegmentedControl.Item>
				{/each}
			</SegmentedControl.Control>
		</SegmentedControl>
		<Popover positioning={{ placement: 'bottom-end' }}>
			<PopoverTriggerButton
				variant="icon"
				class="size-9"
				aria-label={$t('Display options')}
				title={$t('Display options')}><Icon name="settings" size={16} /></PopoverTriggerButton
			>
			<Portal>
				<Popover.Positioner>
					<Popover.Content
						class="z-40 w-64 rounded-xl border border-surface-300-700 bg-surface-50-950 p-4 shadow-xl"
					>
						<label class="flex items-center gap-2 text-xs text-surface-700-300">
							{$t('Density')}
							<select
								class="select w-auto py-1 text-xs"
								value={preferences.density}
								onchange={(event) =>
									save({
										...preferences,
										density: event.currentTarget.value === 'compact' ? 'compact' : 'comfortable'
									})}
							>
								<option value="comfortable">{$t('Comfortable')}</option>
								<option value="compact">{$t('Compact')}</option>
							</select>
						</label>
						{#if showTable}
							<fieldset class="grid grid-cols-1 gap-3">
								<legend class="mt-4 mb-3 font-semibold">{$t('Visible columns')}</legend>
								{#each table
									.getAllLeafColumns()
									.filter((column) => column.getCanHide()) as column (column.id)}
									<label class="flex items-center gap-2 text-sm"
										><input
											type="checkbox"
											checked={column.getIsVisible()}
											onchange={column.getToggleVisibilityHandler()}
										/>{column.columnDef.header}</label
									>
								{/each}
							</fieldset>
						{/if}
						<div class="mt-4 border-t border-surface-300-700 pt-3">
							<Button size="sm" onclick={() => save(defaultLibraryTablePreferences())}
								>{$t('Reset display')}</Button
							>
						</div>
					</Popover.Content>
				</Popover.Positioner>
			</Portal>
		</Popover>
	</div>
</div>

{#if showTable}
	<!-- The scroll region needs a tab stop for native keyboard scrolling. -->
	<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
	<div
		class="max-h-[65vh] table-wrap"
		tabindex="0"
		role="region"
		aria-label={$t('Library Items')}
		{@attach rowHotkeys}
	>
		<!-- Column dimensions come from TanStack's constrained sizing state. -->
		<table
			class="table min-w-(--library-table-width) table-fixed"
			style:--library-table-width={`${table.getTotalSize()}px`}
		>
			<caption class="sr-only">{$t('Library Items')}</caption>
			<colgroup
				>{#each table.getVisibleLeafColumns() as column (column.id)}
					<col
						class="w-(--library-column-width)"
						style:--library-column-width={`${column.getSize()}px`}
					/>
				{/each}</colgroup
			>
			<thead class="sticky top-0 z-10 bg-surface-100-900 text-xs">
				{#each table.getHeaderGroups() as group (group.id)}
					<tr
						>{#each group.headers as header (header.id)}
							{@const field =
								header.column.id === 'title_html'
									? 'title'
									: header.column.id === 'authors'
										? 'author'
										: header.column.id === 'publication_date'
											? 'published'
											: header.column.id === 'publication_title'
												? 'publication'
												: undefined}
							<th
								scope="col"
								class="bg-surface-100-900 px-4 py-3 font-semibold"
								class:relative={header.column.id !== 'preview'}
								class:sticky={header.column.id === 'preview'}
								class:right-0={header.column.id === 'preview'}
								aria-sort={field && sort === field
									? direction === 'asc'
										? 'ascending'
										: 'descending'
									: undefined}
							>
								{#if header.column.id === 'select' || header.column.id === 'preview'}<span
										class="sr-only">{header.column.columnDef.header}</span
									>
								{:else if field}<button
										id={`library-sort-${field}`}
										type="button"
										class="group flex items-center gap-2 text-left hover:text-primary-700-300"
										disabled={busy}
										title={field === 'author' ? $t('Sort by first author or editor') : undefined}
										aria-label={field === 'title'
											? $t('Sort by title')
											: field === 'author'
												? $t('Sort by authors')
												: field === 'publication'
													? $t('Sort by publication')
													: $t('Sort by publication date')}
										onclick={() =>
											onSort(
												field,
												sort === field
													? direction === 'asc'
														? 'desc'
														: 'asc'
													: defaultSortDirection(field)
											)}
										>{header.column.columnDef.header}<span
											class={sort === field
												? 'shrink-0'
												: 'shrink-0 opacity-0 group-hover:opacity-100 group-focus-visible:opacity-100'}
											><Icon
												name={sort === field
													? direction === 'asc'
														? 'arrow-up'
														: 'arrow-down'
													: 'arrows-up-down'}
												size={14}
											/></span
										></button
									>
								{:else}{header.column.columnDef.header}{/if}
								{#if header.column.getCanResize()}
									<button
										type="button"
										class="absolute top-0 right-0 h-full w-2 cursor-col-resize touch-none border-r border-surface-300-700 hover:bg-primary-200-800 focus-visible:bg-primary-200-800"
										aria-label={$t('Resize {name} column', {
											name: String(header.column.columnDef.header)
										})}
										title={$t('Drag to resize. Use arrow keys to adjust; Home to reset.')}
										onmousedown={header.getResizeHandler()}
										ontouchstart={header.getResizeHandler()}
										onkeydown={(event) => resizeWithKeyboard(event, header.column.id)}
									></button>
								{/if}
							</th>
						{/each}</tr
					>
				{/each}
			</thead>
			<tbody>
				{#each table.getRowModel().rows as row (row.id)}
					<tr
						data-library-item={row.id}
						class="focus-within:outline-2 focus-within:-outline-offset-2 focus-within:outline-primary-500 hover:bg-surface-100-900"
						class:bg-primary-50-950={row.getIsSelected()}
					>
						{#each row.getVisibleCells() as cell (cell.id)}
							<td
								class="px-4 align-top"
								class:sticky={cell.column.id === 'preview'}
								class:right-0={cell.column.id === 'preview'}
								class:bg-surface-50-950={cell.column.id === 'preview'}
								class:py-4={preferences.density === 'comfortable'}
							>
								{#if cell.column.id === 'select'}<input
										type="checkbox"
										id={`library-item-${row.id}`}
										data-library-item-select={row.id}
										aria-describedby={`library-item-title-${row.id}`}
										checked={row.getIsSelected()}
										onclick={(event) => selectWithPointer(row.id, event)}
										title={$t('Shift-click an Item checkbox to select a range on this page.')}
										aria-label={selectionLabel(row.original.authors)}
									/>
								{:else if cell.column.id === 'title_html'}<a
										id={`library-item-title-${row.id}`}
										class="block break-words text-surface-950-50 no-underline hover:text-primary-700-300"
										href={resolve(itemHref(row.id))}
										><strong
											class="leading-relaxed font-semibold"
											class:line-clamp-2={preferences.density === 'compact'}
											><RichText html={row.original.title_html} /></strong
										></a
									>
								{:else if cell.column.id === 'authors'}
									<div class="min-w-0 text-surface-600-400">
										{@render authorLinks(row.original)}
									</div>
								{:else if cell.column.id === 'publication_title'}
									<span class="block break-words text-surface-600-400"
										>{@render publicationLink(row.original.publication_title)}</span
									>
								{:else if cell.column.id === 'publication_date'}
									<span class="block break-words text-surface-600-400"
										>{@render dateLink(row.original.publication_date)}</span
									>
								{:else if cell.column.id === 'preview'}<div
										class="flex items-center justify-end gap-1"
									>
										<Button
											variant="icon"
											size="sm"
											aria-label={$t('Preview Item {number}', { number: row.index + 1 })}
											title={$t('Preview Item')}
											aria-expanded={previewItemId === row.id}
											aria-controls={previewItemId === row.id ? 'library-preview' : undefined}
											onclick={(event) => onPreview(row.id, event.currentTarget)}
											><Icon name="panel-right" size={16} /></Button
										>
										<LibraryActionMenu
											itemId={row.id}
											{currentProject}
											disabled={actionsBusy || busy}
											onAction={(action, trigger) => onItemAction(action, row.id, trigger)}
										/>
									</div>
								{:else}<span
										class="block break-words text-surface-600-400"
										class:line-clamp-2={preferences.density === 'compact'}
										>{String(cell.getValue() || '—')}</span
									>{/if}
							</td>
						{/each}
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
{:else}
	<!-- The region is a keyboard entry point; rows retain native checkbox and link semantics. -->
	<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
	<div
		class="divide-y divide-surface-300-700"
		tabindex="0"
		role="region"
		aria-label={$t('Library Items')}
		{@attach rowHotkeys}
	>
		{#each table.getRowModel().rows as row (row.id)}
			<article
				data-library-item={row.id}
				class="grid grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-3 px-4 focus-within:outline-2 focus-within:-outline-offset-2 focus-within:outline-primary-500"
				class:bg-primary-50-950={row.getIsSelected()}
				class:py-4={preferences.density === 'comfortable'}
				class:py-2={preferences.density === 'compact'}
			>
				<input
					type="checkbox"
					id={`library-item-${row.id}`}
					data-library-item-select={row.id}
					aria-describedby={`library-item-title-${row.id}`}
					checked={row.getIsSelected()}
					onclick={(event) => selectWithPointer(row.id, event)}
					title={$t('Shift-click an Item checkbox to select a range on this page.')}
					aria-label={selectionLabel(row.original.authors)}
				/>
				<div class="grid min-w-0 grid-cols-1 gap-1">
					<a
						id={`library-item-title-${row.id}`}
						class="no-underline"
						href={resolve(itemHref(row.id))}
					>
						<strong class="leading-relaxed font-semibold break-words"
							><RichText html={row.original.title_html} /></strong
						>
					</a>
					<div class="min-w-0 text-sm text-surface-600-400">
						{@render authorLinks(row.original)}
					</div>
					<span class="text-xs break-words text-surface-600-400"
						>{@render publicationLink(row.original.publication_title)} · {@render dateLink(
							row.original.publication_date
						)}</span
					>
				</div>
				<div class="flex items-center gap-1">
					<Button
						variant="icon"
						size="sm"
						aria-label={$t('Preview Item {number}', { number: row.index + 1 })}
						title={$t('Preview Item')}
						aria-expanded={previewItemId === row.id}
						aria-controls={previewItemId === row.id ? 'library-preview' : undefined}
						onclick={(event) => onPreview(row.id, event.currentTarget)}
						><Icon name="panel-right" size={16} /></Button
					>
					<LibraryActionMenu
						itemId={row.id}
						{currentProject}
						disabled={actionsBusy || busy}
						onAction={(action, trigger) => onItemAction(action, row.id, trigger)}
					/>
				</div>
			</article>
		{/each}
	</div>
{/if}
