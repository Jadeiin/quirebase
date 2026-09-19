<script lang="ts">
	import type { Snippet } from 'svelte';

	type Spacing = 'default' | 'compact';

	let {
		spacing = 'default',
		actions,
		class: className = '',
		children
	} = $props<{
		spacing?: Spacing;
		actions?: Snippet;
		class?: string;
		children: Snippet;
	}>();

	const spacingClass = $derived(spacing === 'compact' ? 'mb-3' : 'mb-6');
</script>

<header class={`flex items-center justify-between gap-4 ${spacingClass} ${className}`}>
	<div class="min-w-0">{@render children()}</div>
	{#if actions}<div class="flex flex-wrap items-center gap-2">{@render actions()}</div>{/if}
</header>
