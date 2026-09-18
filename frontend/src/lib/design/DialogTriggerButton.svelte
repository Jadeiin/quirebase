<script lang="ts">
	import { Dialog } from '@skeletonlabs/skeleton-svelte';
	import type { Snippet } from 'svelte';
	import { buttonClass, type ButtonVariant } from '$lib/design/button-classes';

	let {
		variant = 'filled',
		class: className = '',
		children
	} = $props<{
		variant?: ButtonVariant;
		class?: string;
		children: Snippet;
	}>();
</script>

<Dialog.Trigger class={`${buttonClass(variant)} ${className}`.trim()}>
	{@render children()}
</Dialog.Trigger>
