<script lang="ts">
	import type { Snippet } from 'svelte';

	let {
		title,
		authors,
		children,
		density = 'standard',
		headingId
	}: {
		title: Snippet;
		authors?: Snippet;
		children?: Snippet;
		density?: 'compact' | 'standard' | 'detailed';
		headingId?: string;
	} = $props();

	const titleClasses = {
		compact: 'line-clamp-2 text-sm leading-5',
		standard: 'block text-base leading-6',
		detailed: 'block text-lg leading-7'
	} as const;
</script>

<div class="grid min-w-0 grid-cols-1 gap-1 wrap-anywhere">
	<svelte:element
		this={headingId ? 'h3' : 'strong'}
		id={headingId}
		class={`m-0 min-w-0 font-semibold ${titleClasses[density]}`}
	>
		{@render title()}
	</svelte:element>
	{#if authors}
		<div
			class="min-w-0 text-surface-600-400"
			class:text-xs={density === 'compact'}
			class:text-sm={density !== 'compact'}
		>
			{@render authors()}
		</div>
	{/if}
	{#if children}
		<div class="min-w-0 text-xs leading-5 text-surface-600-400">
			{@render children()}
		</div>
	{/if}
</div>
