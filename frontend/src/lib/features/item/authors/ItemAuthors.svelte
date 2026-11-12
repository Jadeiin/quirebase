<script lang="ts">
	import { afterNavigate } from '$app/navigation';
	import { Dialog, Portal } from '@skeletonlabs/skeleton-svelte';
	import { tick } from 'svelte';
	import { MediaQuery } from 'svelte/reactivity';
	import { ph, t } from 'lingui-for-svelte/macro';
	import AuthorLine from '#lib/design/AuthorLine.svelte';
	import type { AuthorLineLayout } from '#lib/design/author-line.js';
	import BrandIcon from '#lib/design/BrandIcon.svelte';
	import DialogCloseButton from '#lib/design/DialogCloseButton.svelte';
	import Icon from '#lib/design/Icon.svelte';
	import ItemAuthorDetails from './ItemAuthorDetails.svelte';
	import ItemAuthorPopover from './ItemAuthorPopover.svelte';
	import type { ItemAuthorCredit } from '../metadata-links.js';

	let {
		authors,
		expanded = $bindable(false)
	}: { authors: ItemAuthorCredit[]; expanded?: boolean } = $props();
	const compact = new MediaQuery('(max-width: 767px)');
	const id = $props.id();
	const bylineId = `${id}-authors`;
	const titleId = `${id}-title`;
	let byline = $state<HTMLDivElement>();
	let toggle = $state<HTMLButtonElement>();
	let dialogOpen = $state(false);
	let selected = $state<number | null>(null);
	let opener = $state<HTMLElement | null>(null);
	let activePopover = $state<number | null>(null);
	let lastCompact: boolean | undefined;
	const current = $derived(selected === null ? undefined : authors[selected]);
	let overflowing = $state(true);
	afterNavigate(() => {
		dialogOpen = false;
		activePopover = null;
	});

	function availableTrigger(index: number | null) {
		const candidate =
			index === null
				? null
				: byline?.querySelector<HTMLButtonElement>(`[data-item-author-index="${index}"]`);
		if (candidate?.getClientRects().length) return candidate;
		return (
			toggle ??
			Array.from(
				byline?.querySelectorAll<HTMLButtonElement>('[data-item-author-index]') ?? []
			).find((button) => button.getClientRects().length > 0) ??
			null
		);
	}
	function returnFocus() {
		if (opener?.isConnected && opener.getClientRects().length) return opener;
		return availableTrigger(selected);
	}
	function showAuthor(index: number, trigger: HTMLElement) {
		opener = trigger;
		selected = index;
		dialogOpen = true;
	}
	async function expandAuthors() {
		expanded = true;
		await tick();
		toggle?.focus({ preventScroll: true });
	}
	function onLayoutChange(layout: AuthorLineLayout) {
		const focused = document.activeElement;
		const restore =
			(!layout.overflowing && focused === toggle) ||
			(activePopover !== null &&
				activePopover >= layout.prefixCount &&
				!(layout.lastVisible && activePopover === authors.length - 1));
		if (restore) activePopover = null;
		overflowing = layout.overflowing;
		if (restore) void tick().then(() => availableTrigger(null)?.focus());
	}
	$effect.pre(() => {
		const next = compact.current;
		if (lastCompact !== undefined && next !== lastCompact && byline) {
			const focused = document.activeElement;
			const index = activePopover ?? selected;
			const restore =
				dialogOpen ||
				activePopover !== null ||
				(focused instanceof HTMLElement && byline.contains(focused));
			dialogOpen = false;
			activePopover = null;
			if (restore)
				void tick().then(() =>
					requestAnimationFrame(() => {
						if (document.activeElement !== document.body && document.activeElement !== focused)
							return;
						availableTrigger(index)?.focus();
					})
				);
		}
		lastCompact = next;
	});
</script>

{#snippet credit(index: number)}
	{@const author = authors[index]}
	{#if compact.current}
		<span class="inline-flex max-w-full min-w-0 items-center gap-0.5">
			<button
				type="button"
				class={[
					'min-w-0 rounded-sm text-left hover:text-primary-700-300 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-primary-500',
					expanded ? 'wrap-anywhere' : 'whitespace-nowrap'
				]}
				data-item-author-index={index}
				aria-label={$t`View details for ${ph({ name: author.label })}`}
				aria-haspopup="dialog"
				aria-expanded={dialogOpen && selected === index}
				onclick={(event) => showAuthor(index, event.currentTarget)}>{author.label}</button
			>{#if author.orcidHref}<a
					class="inline-flex size-6 shrink-0 items-center justify-center rounded-sm hover:bg-surface-200-800"
					href={author.orcidHref}
					target="_blank"
					rel="external noopener noreferrer"
					aria-label={$t`View ${ph({ name: author.label })}'s ORCID (opens in a new tab)`}
					title={$t`View ${ph({ name: author.label })}'s ORCID (opens in a new tab)`}
					><BrandIcon name="orcid" /></a
				>{/if}
		</span>
	{:else}
		<ItemAuthorPopover
			{author}
			{index}
			{expanded}
			open={activePopover === index}
			onOpenChange={(index, open) => {
				if (open) activePopover = index;
				else if (activePopover === index) activePopover = null;
			}}
		/>
	{/if}
{/snippet}

<div class="min-w-0 text-surface-700-300" bind:this={byline} data-item-authors>
	<div id={bylineId} class="leading-6" data-author-byline>
		{#if !authors.length}{$t`Unknown authors`}
		{:else if expanded}
			<div class="flex flex-wrap items-center gap-x-1">
				{#each authors as author, index (author)}<span
						class="inline-flex min-h-6 max-w-full items-center gap-0.5"
					>
						{@render credit(index)}{#if index < authors.length - 1}<span aria-hidden="true">;</span
							>{/if}
					</span>{/each}
			</div>
		{:else}
			<AuthorLine
				names={authors.map((author) => author.label)}
				maxRows={compact.current ? 1 : 3}
				onShowAll={expandAuthors}
				{onLayoutChange}
				controls={bylineId}
			>
				{#snippet measurement(index: number)}
					{@const author = authors[index]}
					<span class="inline-flex items-center gap-0.5"
						><span>{author.label}</span>{#if author.orcidHref}<span
								class="inline-flex size-6 shrink-0"
							></span>{/if}</span
					>
				{/snippet}
				{#snippet author(index: number)}{@render credit(index)}{/snippet}
			</AuthorLine>
		{/if}
	</div>
	{#if authors.length && overflowing}<button
			type="button"
			class="mt-1 inline-flex min-h-8 items-center gap-1 rounded-sm text-primary-700-300 hover:text-primary-800-200 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-500"
			bind:this={toggle}
			aria-expanded={expanded}
			aria-controls={bylineId}
			onclick={() => (expanded = !expanded)}
			>{expanded ? $t`Show fewer authors` : $t`Show authors`}<Icon
				name={expanded ? 'chevron-up' : 'chevron-down'}
				size={14}
			/></button
		>{/if}
</div>

<Dialog
	open={dialogOpen}
	ids={{ title: titleId }}
	initialFocusEl={() => document.getElementById(titleId)}
	finalFocusEl={returnFocus}
	onOpenChange={({ open }) => (dialogOpen = open)}
>
	{#if dialogOpen && current}<Portal
			><Dialog.Backdrop class="fixed inset-0 z-70 bg-surface-950/35" /><Dialog.Positioner
				class="fixed inset-0 z-71 grid grid-cols-1 place-items-center p-4"
				><Dialog.Content
					aria-labelledby={titleId}
					class="flex max-h-[80dvh] w-full max-w-md flex-col overflow-hidden rounded-container border border-surface-300-700 bg-surface-50-950 shadow-xl"
					><div class="flex items-start justify-between gap-4 border-b border-surface-300-700 p-5">
						<Dialog.Title
							role="heading"
							aria-level={2}
							tabindex={-1}
							class="m-0 text-lg font-semibold wrap-anywhere">{current.label}</Dialog.Title
						><DialogCloseButton />
					</div>
					<div class="min-h-0 overflow-y-auto p-5">
						<ItemAuthorDetails author={current} />
					</div></Dialog.Content
				></Dialog.Positioner
			></Portal
		>{/if}
</Dialog>
