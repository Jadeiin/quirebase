<script lang="ts">
	import { resolve } from '$app/paths';
	import { t } from '#lib/i18n.js';
	import type { libraryHref, LibraryMetadataFilter } from './filters.js';
	import type { LibrarySearch } from './queries.js';

	let {
		authors,
		filterHref,
		previewOpen,
		onShowAll
	}: {
		authors: LibrarySearch['items'][number]['authors'];
		filterHref: (filter: LibraryMetadataFilter) => ReturnType<typeof libraryHref>;
		previewOpen: boolean;
		onShowAll: (trigger: HTMLElement) => void;
	} = $props();

	let row = $state<HTMLDivElement>();
	let clipped = $state<HTMLSpanElement>();
	let content = $state<HTMLSpanElement>();
	let ellipsis = $state<HTMLButtonElement>();
	let overflowing = $state(false);
	let visibleCount = $state(0);

	$effect(() => {
		const currentAuthors = authors;
		if (!row || !clipped || !content) return;
		const rowElement = row;
		const clippedElement = clipped;
		const contentElement = content;
		const ellipsisElement = ellipsis;
		let frame = 0;
		function measure() {
			// Use the whole row so widening it can remove the ellipsis again.
			const nextOverflow =
				contentElement.getBoundingClientRect().width > rowElement.clientWidth + 0.5;
			if (!nextOverflow && ellipsisElement && document.activeElement === ellipsisElement) {
				contentElement.querySelector('a')?.focus();
			}
			overflowing = nextOverflow;
			const bounds = clippedElement.getBoundingClientRect();
			let count = 0;
			for (const link of contentElement.children) {
				if (link.getBoundingClientRect().left >= bounds.right - 0.5) break;
				count++;
			}
			const focused = document.activeElement;
			if (
				count > 0 &&
				focused instanceof HTMLAnchorElement &&
				focused.parentElement === contentElement &&
				focused.getBoundingClientRect().left >= bounds.right - 0.5
			) {
				contentElement.querySelector('a')?.focus();
			}
			// Fully clipped names must not become invisible keyboard stops.
			visibleCount = count;
		}
		function schedule() {
			cancelAnimationFrame(frame);
			frame = requestAnimationFrame(measure);
		}
		const observer = new ResizeObserver(schedule);
		observer.observe(rowElement);
		observer.observe(clippedElement);
		observer.observe(contentElement);
		if (currentAuthors.length) schedule();
		return () => {
			cancelAnimationFrame(frame);
			observer.disconnect();
		};
	});
</script>

{#if authors.length}
	<div class="flex max-w-full min-w-0 items-baseline" bind:this={row}>
		<span class="min-w-0 overflow-clip" bind:this={clipped}>
			<span class="inline-block w-max whitespace-nowrap" bind:this={content}>
				{#each authors as author, index (index)}
					{index ? '; ' : ''}<a
						dir="auto"
						class="text-surface-700-300 no-underline underline-offset-4 hover:text-primary-700-300 hover:underline focus-visible:underline"
						href={resolve(
							filterHref({
								author_last_name: author.last_name,
								author_first_name: author.first_name ?? ''
							})
						)}
						inert={index >= visibleCount}
						title={$t('View Items by {name}', { name: author.full_name })}
						aria-label={$t('View Items by {name}', { name: author.full_name })}
						>{author.full_name}</a
					>
				{/each}
			</span>
		</span>
		{#if overflowing}
			<button
				bind:this={ellipsis}
				type="button"
				class="shrink-0 px-0.5 text-surface-700-300 hover:text-primary-700-300"
				aria-label={$t('Show all authors')}
				title={$t('Show all authors')}
				aria-expanded={previewOpen}
				aria-controls={previewOpen ? 'library-preview' : undefined}
				onclick={(event) => onShowAll(event.currentTarget)}>…</button
			>
		{/if}
	</div>
{:else}
	<span class="block truncate">{$t('Unknown authors')}</span>
{/if}
