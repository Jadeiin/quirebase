<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { HTMLAttributes } from 'svelte/elements';

	type BadgeElement = 'button' | 'span';
	type BadgeVariant = 'surface' | 'primary' | 'success' | 'warning' | 'error';
	type BadgeProps = {
		as?: BadgeElement;
		variant?: BadgeVariant;
		disabled?: boolean;
		type?: 'button' | 'submit' | 'reset';
		children: Snippet;
	} & HTMLAttributes<HTMLElement>;

	let {
		as = 'span',
		variant = 'surface',
		class: className = '',
		children,
		...rest
	}: BadgeProps = $props();

	const variants: Record<BadgeVariant, string> = {
		surface: 'preset-tonal-surface',
		primary: 'preset-tonal-primary',
		success: 'preset-tonal-success',
		warning: 'preset-tonal-warning',
		error: 'preset-tonal-error'
	};
</script>

<svelte:element this={as} class={`badge ${variants[variant]} ${className}`.trim()} {...rest}>
	{@render children()}
</svelte:element>
