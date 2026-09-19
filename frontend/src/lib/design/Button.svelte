<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { HTMLAnchorAttributes, HTMLButtonAttributes } from 'svelte/elements';
	import { buttonClass, type ButtonVariant } from '$lib/design/button-classes';

	type ButtonElement = 'a' | 'button';
	type ButtonProps = {
		as?: ButtonElement;
		variant?: ButtonVariant;
		size?: 'md' | 'sm';
		children: Snippet;
	} & HTMLButtonAttributes &
		HTMLAnchorAttributes;

	let {
		as = 'button',
		variant = 'tonal',
		size = 'md',
		class: className = '',
		children,
		...rest
	}: ButtonProps = $props();

	const classes = $derived(`${buttonClass(variant, size)} ${className}`.trim());
</script>

<svelte:element this={as} class={classes} {...rest}>
	{@render children()}
</svelte:element>

<style>
	.btn.btn-sm {
		--btn-size: var(--text-sm);
		font-size: var(--text-sm);
		line-height: var(--text-sm);
	}
</style>
