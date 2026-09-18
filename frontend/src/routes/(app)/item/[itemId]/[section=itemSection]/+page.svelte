<script lang="ts">
	import ItemWorkspace from '$lib/features/item/ItemWorkspace.svelte';
	import type { PageProps } from './$types';

	let { params }: PageProps = $props();
</script>

<ItemWorkspace itemId={params.itemId} section={params.section} />
