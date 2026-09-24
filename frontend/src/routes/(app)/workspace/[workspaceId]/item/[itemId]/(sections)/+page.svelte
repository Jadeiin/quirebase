<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import ItemSectionState from '$lib/features/item/ItemSectionState.svelte';
	import { itemDetailsQuery, itemOverviewQuery } from '$lib/features/item/queries';
	import ItemOverviewSection from '$lib/features/item/overview/ItemOverviewSection.svelte';
	import type { PageProps } from './$types';

	let { params }: PageProps = $props();
	const overview = createQuery(() => itemOverviewQuery(params.workspaceId, params.itemId));
	const details = createQuery(() => itemDetailsQuery(params.workspaceId, params.itemId, true));
</script>

<ItemSectionState loading={overview.isPending} failed={overview.isError}>
	<ItemOverviewSection itemId={params.itemId} data={overview.data!} details={details.data} />
</ItemSectionState>
