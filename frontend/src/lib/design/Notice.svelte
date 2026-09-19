<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { HTMLAttributes } from 'svelte/elements';

	type NoticeElement = 'div' | 'p';
	type NoticeVariant = 'error' | 'info' | 'success' | 'warning';
	type NoticeProps = {
		as?: NoticeElement;
		variant?: NoticeVariant;
		role?: string;
		children: Snippet;
	} & HTMLAttributes<HTMLElement>;

	let {
		as = 'p',
		variant = 'info',
		role,
		class: className = '',
		children,
		...rest
	}: NoticeProps = $props();

	const variants: Record<NoticeVariant, string> = {
		error: 'border-error-200-800 bg-error-50-950 text-error-700-300',
		info: 'border-surface-300-700 bg-surface-100-900',
		success: 'preset-tonal-success border-success-200-800 text-success-900-100',
		warning: 'border-warning-700-300 bg-warning-50-950'
	};

	const resolvedRole = $derived(role ?? (variant === 'error' ? 'alert' : 'status'));
</script>

<svelte:element
	this={as}
	class={`rounded-base border px-4 py-3 ${variants[variant]} ${className}`.trim()}
	role={resolvedRole}
	{...rest}
>
	{@render children()}
</svelte:element>
