<script lang="ts">
	import type { HTMLAttributes } from 'svelte/elements';
	import { Navigation } from '@skeletonlabs/skeleton-svelte';
	import type { Snippet } from 'svelte';
	let { label, children }: { label: string; children: Snippet } = $props();
</script>

<Navigation
	layout="bar"
	class="mb-4 overflow-x-auto border-b border-surface-300-700 bg-transparent p-0"
>
	{#snippet element(attributes)}
		<nav {...attributes as HTMLAttributes<HTMLElement>} aria-label={label}>
			<Navigation.Menu class="gap-1">{@render children()}</Navigation.Menu>
		</nav>
	{/snippet}
</Navigation>
