<script lang="ts">
	import { Menu, Portal } from '@skeletonlabs/skeleton-svelte';
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
	class="flex min-h-12 items-center justify-between gap-2 overflow-x-auto border-b border-surface-300 bg-surface-50 px-2 py-1.5"
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
		<form class="flex items-center gap-1 text-xs text-surface-600" onsubmit={goToPage}>
			<input
				class="focus:ring-accent/15 h-8 w-12 rounded-md border border-surface-300 bg-surface-100 text-center text-surface-900 tabular-nums focus:border-primary-700 focus:ring-2 focus:outline-none"
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

	<div class="flex shrink-0 items-center gap-0.5 border-l border-surface-300 pl-2">
		<IconButton label={$t('Zoom out')} icon="minus" onclick={() => zoom.provides?.zoomOut()} />
		<Menu positioning={{ placement: 'bottom', gutter: 6 }}>
			<Menu.Trigger
				class="inline-flex h-9 w-20 cursor-pointer items-center justify-center gap-1 rounded-md text-xs text-surface-700 tabular-nums hover:bg-surface-200 hover:text-primary-800"
			>
				{Math.round(zoom.state.currentZoomLevel * 100)}% <Icon name="chevron-down" size={14} />
			</Menu.Trigger>
			<Portal>
				<Menu.Positioner class="z-100">
					<Menu.Content
						class="min-w-40 rounded-container border border-surface-300 bg-surface-50 p-1 shadow-xl"
					>
						<Menu.Item
							value="fit-width"
							class="flex cursor-pointer items-center rounded-md px-2.5 py-2 text-sm outline-none data-[highlighted]:bg-primary-50 data-[highlighted]:text-primary-800"
							onclick={() => zoom.provides?.requestZoom(ZoomMode.FitWidth)}
							>{$t('Fit width')}</Menu.Item
						>
						<Menu.Item
							value="fit-page"
							class="flex cursor-pointer items-center rounded-md px-2.5 py-2 text-sm outline-none data-[highlighted]:bg-primary-50 data-[highlighted]:text-primary-800"
							onclick={() => zoom.provides?.requestZoom(ZoomMode.FitPage)}
							>{$t('Fit page')}</Menu.Item
						>
						<Menu.Separator class="m-1 h-px bg-surface-300" />
						{#each [0.5, 0.75, 1, 1.25, 1.5, 2] as level (level)}
							<Menu.Item
								value={`zoom-${level}`}
								class="flex cursor-pointer items-center rounded-md px-2.5 py-2 text-sm outline-none data-[highlighted]:bg-primary-50 data-[highlighted]:text-primary-800"
								onclick={() => zoom.provides?.requestZoom(level)}>{level * 100}%</Menu.Item
							>
						{/each}
					</Menu.Content>
				</Menu.Positioner>
			</Portal>
		</Menu>
		<IconButton label={$t('Zoom in')} icon="plus" onclick={() => zoom.provides?.zoomIn()} />
	</div>

	<div class="flex shrink-0 items-center gap-0.5 border-l border-surface-300 pl-2">
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
		<Menu positioning={{ placement: 'bottom-end', gutter: 6 }}>
			<Menu.Trigger
				class="inline-grid size-9 cursor-pointer place-items-center rounded-md border border-transparent hover:border-surface-300 hover:bg-surface-200 hover:text-primary-800"
				aria-label={$t('Page layout')}
			>
				<Icon name="library" />
			</Menu.Trigger>
			<Portal>
				<Menu.Positioner class="z-100">
					<Menu.Content
						class="min-w-44 rounded-container border border-surface-300 bg-surface-50 p-1 shadow-xl"
					>
						<Menu.Item
							value="single-page"
							class="flex cursor-pointer items-center rounded-md px-2.5 py-2 text-sm outline-none data-[highlighted]:bg-primary-50 data-[highlighted]:text-primary-800"
							onclick={() => spread.provides?.setSpreadMode(SpreadMode.None)}
							>{$t('Single page')}</Menu.Item
						>
						<Menu.Item
							value="two-page-spread"
							class="flex cursor-pointer items-center rounded-md px-2.5 py-2 text-sm outline-none data-[highlighted]:bg-primary-50 data-[highlighted]:text-primary-800"
							onclick={() => spread.provides?.setSpreadMode(SpreadMode.Odd)}
							>{$t('Two-page spread')}</Menu.Item
						>
					</Menu.Content>
				</Menu.Positioner>
			</Portal>
		</Menu>
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
		class="flex items-center gap-2 border-b border-surface-300 bg-surface-50 px-3 py-2 shadow-sm"
		onsubmit={runSearch}
	>
		<Icon name="search" />
		<input
			class="min-w-32 flex-1 bg-transparent text-sm outline-none placeholder:text-surface-600"
			bind:value={query}
			placeholder={$t('Search in document')}
			required
		/>
		<span class="text-xs text-surface-600 tabular-nums"
			>{search.state.total
				? `${search.state.activeResultIndex + 1} / ${search.state.total}`
				: ''}</span
		>
		<button
			class="grid size-8 cursor-pointer place-items-center rounded-md hover:bg-surface-200"
			type="button"
			aria-label={$t('Previous search result')}
			onclick={() => search.provides?.previousResult()}>↑</button
		>
		<button
			class="grid size-8 cursor-pointer place-items-center rounded-md hover:bg-surface-200"
			type="button"
			aria-label={$t('Next search result')}
			onclick={() => search.provides?.nextResult()}>↓</button
		>
		<button
			class="grid size-8 cursor-pointer place-items-center rounded-md hover:bg-surface-200"
			type="button"
			aria-label={$t('Close search')}
			onclick={() => (searchOpen = false)}
		>
			<Icon name="close" />
		</button>
	</form>
{/if}
