<script lang="ts">
	import ItemAnnotationsSection from '$lib/features/item/annotations/ItemAnnotationsSection.svelte';
	import type { PageProps } from './$types';

	let { params }: PageProps = $props();
</script>

<ItemAnnotationsSection itemId={params.itemId} />
