<script lang="ts">
	import { hasInlineMath, projectRichText, projectRichTextAsync } from '$lib/design/rich-text';

	let { html } = $props<{ html: string }>();
	type MathProjection = { source: string; result: string };

	let mathProjection = $state.raw<MathProjection | null>(null);
	const projected = $derived(
		mathProjection !== null && mathProjection.source === html
			? mathProjection.result
			: projectRichText(html)
	);

	$effect(() => {
		const source = html;
		let cancelled = false;
		if (!hasInlineMath(source)) return;

		void projectRichTextAsync(source).then((result) => {
			if (!cancelled) mathProjection = { source, result };
		});
		return () => {
			cancelled = true;
		};
	});
</script>

<!-- This is the sole raw-render boundary: canonical HTML is rebuilt through the Web allowlist. -->
<!-- eslint-disable-next-line svelte/no-at-html-tags -->
<span class="rich-text">{@html projected}</span>

<style>
	.rich-text {
		display: contents;
	}
</style>
