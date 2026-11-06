<script lang="ts">
	import type { Snippet } from 'svelte';
	import BrandIcon from '#lib/design/BrandIcon.svelte';

	let {
		href,
		icon = 'external-link',
		children
	}: {
		href: string;
		icon?: string;
		children: Snippet;
	} = $props();
</script>

<a
	{href}
	target="_blank"
	rel="external noopener noreferrer"
	class="inline-flex max-w-full items-center gap-1.5 align-middle underline-offset-4 hover:underline"
>
	<BrandIcon name={icon} size={16} />
	<span class="min-w-0 wrap-anywhere">{@render children()}</span>
</a>
