<script lang="ts">
	import ExternalLink from '#lib/design/ExternalLink.svelte';
	import type { ScholarlyLink } from './scholarly-links.js';

	let { links }: { links: ScholarlyLink[] } = $props();
</script>

<div class="flex min-w-0 flex-col items-start gap-1">
	{#each links as link, index (index)}
		{#if link.href}
			<ExternalLink href={link.href} icon={link.icon}>{link.label}</ExternalLink>
		{:else}
			<span class="wrap-anywhere">{link.label}</span>
		{/if}
	{:else}—{/each}
</div>
