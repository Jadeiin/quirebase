<script lang="ts">
	import { createQuery, useQueryClient } from '@tanstack/svelte-query';
	import ItemHeader from '$lib/features/item/ItemHeader.svelte';
	import { itemOverviewQuery } from '$lib/features/item/queries';
	import { invalidateItem } from '$lib/query/invalidation';
	import { getSession } from '$lib/session';
	import type { LayoutProps } from './$types';

	let { params, children }: LayoutProps = $props();
	const queryClient = useQueryClient();
	const { query: session } = getSession();
	const overview = createQuery(() => itemOverviewQuery(params.workspaceId, params.itemId));

	function refetchItem() {
		return invalidateItem(queryClient, params.workspaceId, params.itemId);
	}
</script>

<ItemHeader
	itemId={params.itemId}
	overview={overview.data}
	user={session.data?.user}
	onChanged={refetchItem}
/>
{@render children()}
