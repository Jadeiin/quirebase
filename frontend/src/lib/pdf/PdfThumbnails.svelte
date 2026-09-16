<script lang="ts">
	import { ThumbImg, ThumbnailsPane } from '@embedpdf/plugin-thumbnail/svelte';
	import { useScroll } from '@embedpdf/plugin-scroll/svelte';
	import { t } from '$lib/i18n';

	let { documentId } = $props<{ documentId: string }>();
	const scroll = useScroll(() => documentId);
</script>

<aside
	class="hidden min-h-0 w-44 shrink-0 flex-col border-r border-line bg-raised sm:flex"
	aria-label={$t('Page thumbnails')}
>
	<div class="flex items-center justify-between border-b border-line px-3 py-2.5 text-xs">
		<strong class="font-semibold">{$t('Pages')}</strong><span class="text-muted"
			>{scroll.state.totalPages}</span
		>
	</div>
	<ThumbnailsPane {documentId} class="min-h-0 flex-1 overflow-auto">
		{#snippet children(meta)}
			<button
				type="button"
				class={`absolute left-1/2 grid -translate-x-1/2 cursor-pointer place-items-center border-0 bg-transparent text-xs transition-colors [&_img]:rounded-sm [&_img]:border-2 [&_img]:bg-white [&_img]:shadow-md ${scroll.state.currentPage === meta.pageIndex + 1 ? 'font-bold text-accent-strong [&_img]:border-accent' : 'text-muted hover:text-accent-strong [&_img]:border-transparent hover:[&_img]:border-accent'}`}
				onclick={() =>
					scroll.provides?.scrollToPage({
						pageNumber: meta.pageIndex + 1,
						behavior: 'smooth'
					})}
			>
				<ThumbImg {documentId} {meta} alt={`${$t('Page')} ${meta.pageIndex + 1}`} />
				<span>{meta.pageIndex + 1}</span>
			</button>
		{/snippet}
	</ThumbnailsPane>
</aside>
