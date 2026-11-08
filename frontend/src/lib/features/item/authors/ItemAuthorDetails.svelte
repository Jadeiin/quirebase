<script lang="ts">
	import { t } from 'lingui-for-svelte/macro';
	import Button from '#lib/design/Button.svelte';
	import Notice from '#lib/design/Notice.svelte';
	import type { ItemAuthorCredit } from '../metadata-links.js';

	let { author }: { author: ItemAuthorCredit } = $props();
</script>

{#await import('./ItemAuthorDetailsContent.svelte')}
	<p role="status" class="text-sm text-surface-600-400">{$t`Loading…`}</p>
{:then { default: Content }}
	<Content {author} />
{:catch}
	<Notice as="div" variant="error" class="my-3 flex flex-wrap items-center justify-between gap-3">
		<span>{$t`Unable to load author details.`}</span>
		<Button type="button" onclick={() => location.reload()}>{$t`Refresh page`}</Button>
	</Notice>
{/await}
