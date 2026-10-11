<script lang="ts">
	import { Navigation } from '@skeletonlabs/skeleton-svelte';
	import type { Snippet } from 'svelte';

	let {
		href,
		current = false,
		children
	} = $props<{
		href: string;
		current?: boolean;
		children: Snippet;
	}>();
</script>

<!-- eslint-disable svelte/no-navigation-without-resolve -- callers resolve route ids before passing href -->
<Navigation.TriggerAnchor
	class="rounded-none border-b-2 border-transparent bg-transparent px-3 py-2.5 whitespace-nowrap no-underline hover:text-primary-700-300 aria-[current=page]:border-primary-700-300 aria-[current=page]:text-primary-700-300"
	{href}
	aria-current={current ? 'page' : undefined}
>
	{@render children()}
</Navigation.TriggerAnchor>
<!-- eslint-enable svelte/no-navigation-without-resolve -->
