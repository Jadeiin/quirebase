<script lang="ts">
	import { projectRichText } from '$lib/design/rich-text';

	let { html } = $props<{ html: string }>();
	const projected = $derived(projectRichText(html));
</script>

<!-- This is the sole raw-render boundary: canonical HTML is rebuilt through the Web allowlist. -->
<!-- eslint-disable-next-line svelte/no-at-html-tags -->
<span class="rich-text">{@html projected}</span>

<style>
	.rich-text {
		display: contents;
	}
</style>
