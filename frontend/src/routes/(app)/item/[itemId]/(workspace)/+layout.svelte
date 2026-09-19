<script lang="ts">
	import { createQuery, useQueryClient } from '@tanstack/svelte-query';
	import ItemWorkspaceHeader from '$lib/features/item/ItemWorkspaceHeader.svelte';
	import { itemWorkspaceQuery } from '$lib/features/item/queries';
	import { invalidateItem } from '$lib/query/invalidation';
	import { getSession } from '$lib/session';
	import type { LayoutProps } from './$types';

	let { params, children }: LayoutProps = $props();
	const queryClient = useQueryClient();
	const { query: session } = getSession();
	const workspace = createQuery(() => itemWorkspaceQuery(params.itemId));

	function refetchItem() {
		return invalidateItem(queryClient, params.itemId);
	}
</script>

<ItemWorkspaceHeader
	itemId={params.itemId}
	workspace={workspace.data}
	user={session.data?.user}
	onChanged={refetchItem}
/>
{@render children()}
