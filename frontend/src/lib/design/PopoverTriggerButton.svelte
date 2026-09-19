<script lang="ts">
	import { Popover } from '@skeletonlabs/skeleton-svelte';
	import type { Snippet } from 'svelte';
	import type { HTMLAttributes } from 'svelte/elements';
	import { buttonClass, type ButtonVariant } from '$lib/design/button-classes';

	let {
		variant = 'tonal',
		class: className = '',
		children,
		...rest
	} = $props<
		{
			variant?: ButtonVariant;
			class?: string;
			children: Snippet;
		} & HTMLAttributes<HTMLElement>
	>();
</script>

<Popover.Trigger class={`${buttonClass(variant)} ${className}`.trim()} {...rest}>
	{@render children()}
</Popover.Trigger>
