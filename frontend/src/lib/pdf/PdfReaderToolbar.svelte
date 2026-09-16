<script lang="ts">
	import { DropdownMenu } from 'bits-ui';
	import { useHistoryCapability } from '@embedpdf/plugin-history/svelte';
	import { usePan } from '@embedpdf/plugin-pan/svelte';
	import { useRotate } from '@embedpdf/plugin-rotate/svelte';
	import { useScroll } from '@embedpdf/plugin-scroll/svelte';
	import { useSearch } from '@embedpdf/plugin-search/svelte';
	import { SpreadMode, useSpread } from '@embedpdf/plugin-spread/svelte';
	import { ZoomMode, useZoom } from '@embedpdf/plugin-zoom/svelte';
	import Icon from '$lib/design/Icon.svelte';
	import IconButton from '$lib/design/IconButton.svelte';
	import { t } from '$lib/i18n';

	let { documentId, thumbnailsOpen = $bindable(false) } = $props<{
		documentId: string;
		thumbnailsOpen?: boolean;
	}>();
	const scroll = useScroll(() => documentId);
	const zoom = useZoom(() => documentId);
	const rotate = useRotate(() => documentId);
	const pan = usePan(() => documentId);
	const spread = useSpread(() => documentId);
	const search = useSearch(() => documentId);
	const history = useHistoryCapability();
	let pageNumber = $derived(scroll.state.currentPage || 1);
	let searchOpen = $state(false);
	let query = $state('');

	function goToPage(event: SubmitEvent) {
		event.preventDefault();
		scroll.provides?.scrollToPage({ pageNumber, behavior: 'smooth' });
	}

	function runSearch(event: SubmitEvent) {
		event.preventDefault();
		search.provides?.startSearch();
		search.provides?.searchAllPages(query);
	}
</script>

<div
	class="flex min-h-12 items-center justify-between gap-2 overflow-x-auto border-b border-line bg-raised px-2 py-1.5"
	aria-label={$t('PDF reader controls')}
>
	<div class="flex shrink-0 items-center gap-0.5">
		<IconButton
			label={$t('Toggle page thumbnails')}
			icon="panel"
			active={thumbnailsOpen}
			onclick={() => (thumbnailsOpen = !thumbnailsOpen)}
		/>
		<IconButton
			label={$t('Previous page')}
			icon="chevron-left"
			disabled={scroll.state.currentPage <= 1}
			onclick={() => scroll.provides?.scrollToPreviousPage('smooth')}
		/>
		<form class="flex items-center gap-1 text-xs text-muted" onsubmit={goToPage}>
			<input
				class="h-8 w-12 rounded-md border border-line bg-surface text-center text-ink tabular-nums focus:border-accent focus:ring-2 focus:ring-accent/15 focus:outline-none"
				aria-label={$t('Page number')}
				type="number"
				min="1"
				max={scroll.state.totalPages || 1}
				bind:value={pageNumber}
			/>
			<span>/ {scroll.state.totalPages || '—'}</span>
		</form>
		<IconButton
			label={$t('Next page')}
			icon="chevron-right"
			disabled={scroll.state.currentPage >= scroll.state.totalPages}
			onclick={() => scroll.provides?.scrollToNextPage('smooth')}
		/>
	</div>

	<div class="flex shrink-0 items-center gap-0.5 border-l border-line pl-2">
		<IconButton label={$t('Zoom out')} icon="minus" onclick={() => zoom.provides?.zoomOut()} />
		<DropdownMenu.Root>
			<DropdownMenu.Trigger
				class="inline-flex h-9 w-20 cursor-pointer items-center justify-center gap-1 rounded-md text-xs text-secondary tabular-nums hover:bg-muted-surface hover:text-accent-strong"
			>
				{Math.round(zoom.state.currentZoomLevel * 100)}% <Icon name="chevron-down" size={14} />
			</DropdownMenu.Trigger>
			<DropdownMenu.Portal>
				<DropdownMenu.Content
					class="z-100 min-w-40 rounded-lg border border-line bg-raised p-1 shadow-xl"
					sideOffset={6}
					align="center"
				>
					<DropdownMenu.Item
						class="flex cursor-pointer items-center rounded-md px-2.5 py-2 text-sm outline-none data-[highlighted]:bg-accent-soft data-[highlighted]:text-accent-strong"
						onclick={() => zoom.provides?.requestZoom(ZoomMode.FitWidth)}
						>{$t('Fit width')}</DropdownMenu.Item
					>
					<DropdownMenu.Item
						class="flex cursor-pointer items-center rounded-md px-2.5 py-2 text-sm outline-none data-[highlighted]:bg-accent-soft data-[highlighted]:text-accent-strong"
						onclick={() => zoom.provides?.requestZoom(ZoomMode.FitPage)}
						>{$t('Fit page')}</DropdownMenu.Item
					>
					<DropdownMenu.Separator class="m-1 h-px bg-line" />
					{#each [0.5, 0.75, 1, 1.25, 1.5, 2] as level (level)}
						<DropdownMenu.Item
							class="flex cursor-pointer items-center rounded-md px-2.5 py-2 text-sm outline-none data-[highlighted]:bg-accent-soft data-[highlighted]:text-accent-strong"
							onclick={() => zoom.provides?.requestZoom(level)}>{level * 100}%</DropdownMenu.Item
						>
					{/each}
				</DropdownMenu.Content>
			</DropdownMenu.Portal>
		</DropdownMenu.Root>
		<IconButton label={$t('Zoom in')} icon="plus" onclick={() => zoom.provides?.zoomIn()} />
	</div>

	<div class="flex shrink-0 items-center gap-0.5 border-l border-line pl-2">
		<IconButton
			label={$t('Pan tool')}
			icon="hand"
			active={pan.isPanning}
			onclick={() => pan.provides?.togglePan()}
		/>
		<IconButton
			label={$t('Rotate clockwise')}
			icon="rotate"
			onclick={() => rotate.provides?.rotateForward()}
		/>
		<IconButton
			label={$t('Undo')}
			icon="undo"
			disabled={!history.provides?.canUndo()}
			onclick={() => history.provides?.undo()}
		/>
		<IconButton
			label={$t('Redo')}
			icon="redo"
			disabled={!history.provides?.canRedo()}
			onclick={() => history.provides?.redo()}
		/>
		<DropdownMenu.Root>
			<DropdownMenu.Trigger
				class="inline-grid size-9 cursor-pointer place-items-center rounded-md border border-transparent hover:border-line hover:bg-muted-surface hover:text-accent-strong"
				aria-label={$t('Page layout')}
			>
				<Icon name="library" />
			</DropdownMenu.Trigger>
			<DropdownMenu.Portal>
				<DropdownMenu.Content
					class="z-100 min-w-44 rounded-lg border border-line bg-raised p-1 shadow-xl"
					sideOffset={6}
					align="end"
				>
					<DropdownMenu.Item
						class="flex cursor-pointer items-center rounded-md px-2.5 py-2 text-sm outline-none data-[highlighted]:bg-accent-soft data-[highlighted]:text-accent-strong"
						onclick={() => spread.provides?.setSpreadMode(SpreadMode.None)}
						>{$t('Single page')}</DropdownMenu.Item
					>
					<DropdownMenu.Item
						class="flex cursor-pointer items-center rounded-md px-2.5 py-2 text-sm outline-none data-[highlighted]:bg-accent-soft data-[highlighted]:text-accent-strong"
						onclick={() => spread.provides?.setSpreadMode(SpreadMode.Odd)}
						>{$t('Two-page spread')}</DropdownMenu.Item
					>
				</DropdownMenu.Content>
			</DropdownMenu.Portal>
		</DropdownMenu.Root>
		<IconButton
			label={$t('Search document')}
			icon="search"
			active={searchOpen}
			onclick={() => (searchOpen = !searchOpen)}
		/>
	</div>
</div>

{#if searchOpen}
	<form
		class="flex items-center gap-2 border-b border-line bg-raised px-3 py-2 shadow-sm"
		onsubmit={runSearch}
	>
		<Icon name="search" />
		<input
			class="min-w-32 flex-1 bg-transparent text-sm outline-none placeholder:text-muted"
			bind:value={query}
			placeholder={$t('Search in document')}
			required
		/>
		<span class="text-xs text-muted tabular-nums"
			>{search.state.total
				? `${search.state.activeResultIndex + 1} / ${search.state.total}`
				: ''}</span
		>
		<button
			class="grid size-8 cursor-pointer place-items-center rounded-md hover:bg-muted-surface"
			type="button"
			aria-label={$t('Previous search result')}
			onclick={() => search.provides?.previousResult()}>↑</button
		>
		<button
			class="grid size-8 cursor-pointer place-items-center rounded-md hover:bg-muted-surface"
			type="button"
			aria-label={$t('Next search result')}
			onclick={() => search.provides?.nextResult()}>↓</button
		>
		<button
			class="grid size-8 cursor-pointer place-items-center rounded-md hover:bg-muted-surface"
			type="button"
			aria-label={$t('Close search')}
			onclick={() => (searchOpen = false)}
		>
			<Icon name="close" />
		</button>
	</form>
{/if}
