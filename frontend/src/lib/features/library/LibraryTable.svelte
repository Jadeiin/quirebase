<script lang="ts">
	import { resolve } from '$app/paths';
	import type { Snippet } from 'svelte';
	import { MediaQuery } from 'svelte/reactivity';
	import { Popover, Portal, SegmentedControl } from '@skeletonlabs/skeleton-svelte';
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
	import { workspaceHref } from '#lib/workspaces/href.js';
	import type { LibrarySearch } from './queries';
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
		workspaceId,
		filterHref,
		selected,
		onSelectionChange,
		onPreview,
		previewItemId,
		sort,
		direction,
		onSort,
		busy
	}: {
		items: LibrarySearch['items'];
		toolbar: Snippet;
		workspaceId: string;
		filterHref: (filter: LibraryMetadataFilter) => ReturnType<typeof libraryHref>;
		selected: Set<string>;
		onSelectionChange: (ids: string[]) => void;
		onPreview: (id: string, trigger: HTMLElement) => void;
		previewItemId: string;
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
			header: $t('Preview'),
			size: 52,
			minSize: 52,
			maxSize: 52,
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
</script>

{#snippet authorLinks(authors: LibrarySearch['items'][number]['authors'])}
	{#each authors as author, index (index)}
		{index > 0 ? '; ' : ''}<a
			class="text-surface-700-300 no-underline underline-offset-4 hover:text-primary-700-300 hover:underline focus-visible:underline"
			href={resolve(
				filterHref({
					author_last_name: author.last_name,
					author_first_name: author.first_name ?? ''
				})
			)}
			title={$t('View Items by {name}', { name: author.full_name })}
			aria-label={$t('View Items by {name}', { name: author.full_name })}>{author.full_name}</a
		>
	{:else}{$t('Unknown authors')}{/each}
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
			onchange={table.getToggleAllRowsSelectedHandler()}
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
	<div class="max-h-[65vh] table-wrap" tabindex="0" role="region" aria-label={$t('Library Items')}>
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
					<tr class="hover:bg-surface-100-900" class:bg-primary-50-950={row.getIsSelected()}>
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
										checked={row.getIsSelected()}
										onclick={row.getToggleSelectedHandler()}
										aria-label={row.original.authors.length
											? $t('Select {name}', {
													name: row.original.authors.map((author) => author.full_name).join('; ')
												})
											: $t('Select')}
									/>
								{:else if cell.column.id === 'title_html'}<a
										class="block break-words text-surface-950-50 no-underline hover:text-primary-700-300"
										href={resolve(workspaceHref(workspaceId, `item/${row.id}`))}
										><strong
											class="leading-relaxed font-semibold"
											class:line-clamp-2={preferences.density === 'compact'}
											><RichText html={row.original.title_html} /></strong
										></a
									>
								{:else if cell.column.id === 'authors'}
									<span class="block break-words text-surface-600-400"
										>{@render authorLinks(row.original.authors)}</span
									>
								{:else if cell.column.id === 'publication_title'}
									<span class="block break-words text-surface-600-400"
										>{@render publicationLink(row.original.publication_title)}</span
									>
								{:else if cell.column.id === 'publication_date'}
									<span class="block break-words text-surface-600-400"
										>{@render dateLink(row.original.publication_date)}</span
									>
								{:else if cell.column.id === 'preview'}<Button
										variant="icon"
										size="sm"
										aria-label={$t('Preview Item {number}', { number: row.index + 1 })}
										title={$t('Preview Item')}
										aria-expanded={previewItemId === row.id}
										aria-controls={previewItemId === row.id ? 'library-preview' : undefined}
										onclick={(event) => onPreview(row.id, event.currentTarget)}
										><Icon name="panel-right" size={16} /></Button
									>
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
	<div class="divide-y divide-surface-300-700">
		{#each table.getRowModel().rows as row (row.id)}
			<article
				class="grid grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-3 px-4"
				class:py-4={preferences.density === 'comfortable'}
				class:py-2={preferences.density === 'compact'}
			>
				<input
					type="checkbox"
					checked={row.getIsSelected()}
					onclick={row.getToggleSelectedHandler()}
					aria-label={row.original.authors.length
						? $t('Select {name}', {
								name: row.original.authors.map((author) => author.full_name).join('; ')
							})
						: $t('Select')}
				/>
				<div class="grid min-w-0 grid-cols-1 gap-1">
					<a class="no-underline" href={resolve(workspaceHref(workspaceId, `item/${row.id}`))}>
						<strong class="leading-relaxed font-semibold break-words"
							><RichText html={row.original.title_html} /></strong
						>
					</a>
					<span class="text-sm break-words text-surface-600-400"
						>{@render authorLinks(row.original.authors)}</span
					>
					<span class="text-xs break-words text-surface-600-400"
						>{@render publicationLink(row.original.publication_title)} · {@render dateLink(
							row.original.publication_date
						)}</span
					>
				</div>
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
			</article>
		{/each}
	</div>
{/if}
