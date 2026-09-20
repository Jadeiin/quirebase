<script lang="ts">
	import { createMutation, createQuery } from '@tanstack/svelte-query';
	import { apiRequest } from '$lib/api/client';
	import { apiErrorMessage } from '$lib/api/errors';
	import ConfirmDialog from '$lib/design/ConfirmDialog.svelte';
	import Pagination from '$lib/design/Pagination.svelte';
	import AdminItems from '$lib/features/admin/AdminItems.svelte';
	import AdminNotices from '$lib/features/admin/AdminNotices.svelte';
	import AdminSectionState from '$lib/features/admin/AdminSectionState.svelte';
	import { getAdminFilters } from '$lib/features/admin/filters';
	import { adminMutationOptions } from '$lib/features/admin/mutations';
	import { adminItemsQuery } from '$lib/features/admin/queries';
	import { msg, t, type MessageKey } from '$lib/i18n';

	let error = $state('');
	let notice = $state<MessageKey | null>(null);
	let pendingItemId = $state<string | null>(null);
	let confirmDeleteOpen = $state(false);
	const { filters, setPage } = getAdminFilters();
	const items = createQuery(() => adminItemsQuery(filters(), true));
	const adminMutation = createMutation(() => adminMutationOptions('items', () => items.refetch()));
	const busy = $derived(adminMutation.isPending);
	const pageCount = $derived(
		items.data?.total && items.data.per_page
			? Math.max(1, Math.ceil(items.data.total / items.data.per_page))
			: 1
	);

	function mutate(operation: () => Promise<unknown>, success: MessageKey) {
		error = '';
		notice = null;
		void adminMutation
			.mutateAsync({ run: operation })
			.then(() => {
				notice = success;
			})
			.catch((reason) => {
				error = apiErrorMessage(reason, $t('Administration action failed'));
			});
	}

	function deleteAdminItem(itemId: string) {
		pendingItemId = itemId;
		confirmDeleteOpen = true;
	}

	function confirmDeleteAdminItem() {
		const itemId = pendingItemId;
		pendingItemId = null;
		confirmDeleteOpen = false;
		if (!itemId) return;
		void mutate(
			() =>
				apiRequest('DELETE', '/admin/items/{item_id}', {
					params: { path: { item_id: itemId } }
				}),
			msg('Item deleted')
		);
	}
</script>

<AdminNotices {error} {notice} />
<AdminSectionState loading={items.isPending} failed={items.isError} label={msg('Items')}>
	<AdminItems items={items.data!} {busy} onDelete={deleteAdminItem} />
	<ConfirmDialog
		bind:open={confirmDeleteOpen}
		title={$t('Permanently delete this Item?')}
		body={$t('This cannot be undone.')}
		confirmLabel={$t('Permanently delete')}
		{busy}
		onConfirm={confirmDeleteAdminItem}
	/>
	{#if pageCount > 1}
		<Pagination
			page={filters().page}
			{pageCount}
			label={$t('Administration pages')}
			onPage={setPage}
		/>
	{/if}
</AdminSectionState>
