<script lang="ts">
	import PdfWorkspace from '$lib/features/pdf-reader/PdfWorkspace.svelte';
	import type { PageProps } from './$types';

	let { params }: PageProps = $props();
</script>

<PdfWorkspace itemId={params.itemId} revisionId={params.revisionId} />
