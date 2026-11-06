<script module lang="ts">
	import arxivUrl from 'academicons/svg/arxiv.svg?url';
	import doiUrl from 'academicons/svg/doi.svg?url';
	import orcidUrl from 'academicons/svg/orcid.svg?url';
	import pubmedUrl from 'academicons/svg/pubmed.svg?url';
	import rorUrl from 'academicons/svg/ror.svg?url';

	const icons: Record<string, string> = {
		arxiv: arxivUrl,
		doi: doiUrl,
		orcid: orcidUrl,
		pubmed: pubmedUrl,
		ror: rorUrl
	};
</script>

<script lang="ts">
	import Icon from '#lib/design/Icon.svelte';

	let { name, size = 16 }: { name: string; size?: number } = $props();
	const url = $derived(icons[name]);
</script>

{#if url}
	<img
		src={url}
		alt=""
		width={size}
		height={size}
		class="block shrink-0 object-contain dark:invert"
		aria-hidden="true"
	/>
{:else}
	<Icon {name} {size} />
{/if}
