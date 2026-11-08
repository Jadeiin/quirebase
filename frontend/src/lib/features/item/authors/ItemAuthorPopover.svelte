<script lang="ts">
	import { Popover, Portal } from '@skeletonlabs/skeleton-svelte';
	import { ph, t } from 'lingui-for-svelte/macro';
	import BrandIcon from '#lib/design/BrandIcon.svelte';
	import PopoverCloseButton from '#lib/design/PopoverCloseButton.svelte';
	import ItemAuthorDetails from './ItemAuthorDetails.svelte';
	import type { ItemAuthorCredit } from '../metadata-links.js';

	let {
		author,
		index,
		expanded,
		open,
		onOpenChange
	}: {
		author: ItemAuthorCredit;
		index: number;
		expanded: boolean;
		open: boolean;
		onOpenChange: (index: number, open: boolean) => void;
	} = $props();
	const id = $props.id();
	const titleId = `${id}-title`;
</script>

<span class="inline-flex max-w-full min-w-0 items-center gap-0.5 align-middle">
	<Popover
		{open}
		ids={{ title: titleId }}
		initialFocusEl={() => document.getElementById(titleId)}
		positioning={{ placement: 'bottom-start', gutter: 12, overflowPadding: 16 }}
		onOpenChange={(details) => {
			onOpenChange(index, details.open);
		}}
	>
		<Popover.Trigger
			class={[
				'min-w-0 rounded-sm text-left hover:text-primary-700-300 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-primary-500',
				expanded ? 'wrap-anywhere' : 'whitespace-nowrap'
			]}
			data-item-author-index={index}
			aria-label={$t`View details for ${ph({ name: author.label })}`}
			>{author.label}</Popover.Trigger
		>
		{#if open}<Portal
				><Popover.Positioner class="z-65"
					><Popover.Content
						aria-labelledby={titleId}
						class="max-h-[70dvh] w-[min(24rem,calc(100vw-2rem))] overflow-y-auto rounded-container border border-surface-300-700 bg-surface-50-950 p-5 shadow-xl"
						><div class="mb-4 flex items-start justify-between gap-4">
							<Popover.Title
								role="heading"
								aria-level={2}
								tabindex={-1}
								class="m-0 text-lg font-semibold wrap-anywhere">{author.label}</Popover.Title
							><PopoverCloseButton />
						</div>
						<ItemAuthorDetails {author} /></Popover.Content
					></Popover.Positioner
				></Portal
			>{/if}
	</Popover>
	{#if author.orcidHref}<a
			class="inline-flex size-6 shrink-0 items-center justify-center rounded-sm hover:bg-surface-200-800"
			href={author.orcidHref}
			target="_blank"
			rel="external noopener noreferrer"
			aria-label={$t`View ${ph({ name: author.label })}'s ORCID (opens in a new tab)`}
			title={$t`View ${ph({ name: author.label })}'s ORCID (opens in a new tab)`}
			><BrandIcon name="orcid" /></a
		>{/if}
</span>
