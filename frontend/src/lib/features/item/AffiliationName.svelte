<script lang="ts">
	import { resolve } from '$app/paths';
	import { ph, t } from 'lingui-for-svelte/macro';
	import type { affiliationLinks } from './metadata-links.js';
	let {
		affiliation
	}: {
		affiliation: Pick<
			ReturnType<typeof affiliationLinks>[number],
			'name' | 'identifier' | 'rorFilterHref'
		>;
	} = $props();
	const label = $derived(affiliation.name || affiliation.identifier.label);
</script>

{#if affiliation.rorFilterHref}
	<a
		class="wrap-anywhere text-primary-700-300 underline-offset-4 hover:underline focus-visible:underline"
		href={resolve(affiliation.rorFilterHref)}
		title={$t`Filter Library by this ROR: ${ph({ institution: label })}`}>{label}</a
	>
{:else if affiliation.name}
	<span class="wrap-anywhere">{affiliation.name}</span>
{/if}
