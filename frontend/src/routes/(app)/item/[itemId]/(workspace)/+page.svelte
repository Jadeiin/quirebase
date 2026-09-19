<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import ItemSectionState from '$lib/features/item/ItemSectionState.svelte';
	import { itemDetailsQuery, itemWorkspaceQuery } from '$lib/features/item/queries';
	import ItemOverviewSection from '$lib/features/item/overview/ItemOverviewSection.svelte';
	import type { PageProps } from './$types';

	let { params }: PageProps = $props();
	const workspace = createQuery(() => itemWorkspaceQuery(params.itemId));
	const details = createQuery(() => itemDetailsQuery(params.itemId, true));
</script>

<ItemSectionState loading={workspace.isPending} failed={workspace.isError}>
	<ItemOverviewSection itemId={params.itemId} data={workspace.data!} details={details.data} />
</ItemSectionState>
