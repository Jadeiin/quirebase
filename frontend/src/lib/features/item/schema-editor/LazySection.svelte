<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { HTMLDetailsAttributes } from 'svelte/elements';

	let {
		open = $bindable(false),
		reveal = 0,
		summary,
		children,
		...attributes
	}: Omit<HTMLDetailsAttributes, 'children'> & {
		reveal?: number;
		summary: Snippet;
		children: Snippet;
	} = $props();
	let mounted = $state(false);
	$effect(() => {
		if (open) mounted = true;
	});
	$effect(() => {
		// A new request also reopens a section the user previously closed.
		if (reveal) open = true;
	});
</script>

<details {...attributes} bind:open>
	{@render summary()}
	{#if open || mounted}{@render children()}{/if}
</details>
