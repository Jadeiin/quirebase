<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { HTMLAttributes } from 'svelte/elements';

	type ItemRowElement = 'a' | 'article' | 'div';
	type ItemRowProps = {
		as?: ItemRowElement;
		href?: string;
		children: Snippet;
	} & HTMLAttributes<HTMLElement>;

	let { as = 'div', class: className = '', children, ...rest }: ItemRowProps = $props();

	const base = 'grid gap-1 border-b border-surface-300-700 py-[0.85rem] last:border-b-0';
	const classes = $derived(
		`${base} ${as === 'a' ? 'no-underline hover:text-primary-800-200' : ''} ${className}`.trim()
	);
</script>

<svelte:element this={as} class={classes} {...rest}>
	{@render children()}
</svelte:element>
