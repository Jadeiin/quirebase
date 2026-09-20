<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { HTMLAttributes } from 'svelte/elements';

	type PanelElement = 'a' | 'article' | 'aside' | 'div' | 'form' | 'section';
	type PanelProps = {
		as?: PanelElement;
		padding?: 'md' | 'sm' | 'none';
		href?: string;
		children: Snippet;
	} & HTMLAttributes<HTMLElement>;

	let {
		as = 'section',
		padding = 'md',
		class: className = '',
		children,
		...rest
	}: PanelProps = $props();

	const paddingClass = { md: 'p-5', sm: 'p-2', none: 'overflow-hidden' } as const;
</script>

<svelte:element
	this={as}
	class={`card border border-surface-300-700 bg-surface-50-950 shadow-sm ${paddingClass[padding]} ${className}`}
	{...rest}
>
	{@render children()}
</svelte:element>
