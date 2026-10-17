<script lang="ts">
	import { createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { ApiError, apiRequest } from '#lib/api/client.js';
	import { apiErrorMessage } from '#lib/api/errors.js';
	import type { components } from '#lib/api/schema.js';
	import Button from '#lib/design/Button.svelte';
	import Notice from '#lib/design/Notice.svelte';
	import SearchSelect from '#lib/design/SearchSelect.svelte';
	import { adminUsersQuery } from '#lib/features/admin/queries.js';
	import { invalidateWorkspaces } from '#lib/query/invalidation.js';
	import { t } from '#lib/i18n.js';

	let {
		workspace,
		onClose
	}: {
		workspace: components['schemas']['AdminWorkspaceView'];
		onClose: () => void;
	} = $props();
	const queryClient = useQueryClient();
	let search = $state<string | null>(null);
	let receiverId = $state('');
	let selectedUser = $state<components['schemas']['AdminUserView']>();
	let reason = $state('');
	let busy = $state(false);
	let error = $state('');
	const users = createQuery(() =>
		adminUsersQuery({
			page: 1,
			pageSize: 20,
			search: search ?? '',
			filterA: '',
			filterB: 'true'
		})
	);
	function selectReceiver(userId: string) {
		// Capture the selection before SearchSelect clears the search and changes the query.
		selectedUser =
			users.data?.items.find((user) => user.id === userId) ??
			(selectedUser?.id === userId ? selectedUser : undefined);
		receiverId = userId;
	}

	async function reassign(event: SubmitEvent) {
		event.preventDefault();
		if (!receiverId || reason.trim().length < 10 || !workspace.can_reassign_owner) return;
		busy = true;
		error = '';
		try {
			await apiRequest('POST', '/admin/workspaces/{workspace_id}/owner', {
				params: { path: { workspace_id: workspace.id } },
				body: {
					new_owner_user_id: receiverId,
					expected_owner_user_id: workspace.owner_id,
					reason: reason.trim()
				}
			});
			await Promise.all([
				queryClient.invalidateQueries({ queryKey: ['admin'] }),
				invalidateWorkspaces(queryClient)
			]);
			onClose();
		} catch (failure) {
			if (failure instanceof ApiError && failure.code === 'version_conflict') {
				error = $t(
					'Ownership changed. Review the refreshed owner and submit again. Your draft is preserved.'
				);
				await queryClient.invalidateQueries({ queryKey: ['admin', 'workspaces'] });
			} else error = apiErrorMessage(failure, 'Workspace governance action failed');
		} finally {
			busy = false;
		}
	}
</script>

<form
	class="grid w-full min-w-0 grid-cols-1 gap-3 border-t border-surface-300-700 pt-4"
	onsubmit={reassign}
>
	<h3 class="font-semibold">{$t('Reassign owner')}</h3>
	<p class="text-sm text-surface-600-400">
		{$t(
			'The selected user gains Workspace owner access. The previous owner becomes a Workspace admin. This does not disable the previous account.'
		)}
	</p>
	<p class="text-sm">{$t('Current owner: {username}', { username: workspace.owner_username })}</p>
	{#if error}<Notice variant="error">{error}</Notice>{/if}
	{#if users.isError}<Notice variant="error"
			>{apiErrorMessage(users.error, 'Failed to load users')}</Notice
		>{/if}
	<SearchSelect
		label={$t('New owner')}
		emptyLabel={$t('Search active users')}
		bind:value={() => receiverId, selectReceiver}
		bind:search
		selectedLabel={selectedUser?.id === receiverId ? selectedUser.username : undefined}
		options={(users.data?.items ?? []).map((user) => ({ value: user.id, label: user.username }))}
		filterOptions={false}
		loading={users.isFetching}
		disabled={busy}
		required
	/>
	<p class="text-xs text-surface-600-400">
		{$t('Showing up to 20 active users. Type to narrow the search.')}
	</p>
	<label class="grid grid-cols-1 gap-1">
		{$t('Reason (at least 10 characters)')}
		<textarea
			class="input"
			bind:value={reason}
			minlength="10"
			maxlength="1000"
			disabled={busy}
			required></textarea>
	</label>
	<div class="flex flex-wrap gap-2">
		<Button
			variant="filled"
			disabled={busy ||
				!workspace.can_reassign_owner ||
				!receiverId ||
				receiverId === workspace.owner_id ||
				reason.trim().length < 10}
		>
			{$t('Confirm owner reassignment')}
		</Button>
		<Button type="button" disabled={busy} onclick={onClose}>{$t('Cancel')}</Button>
	</div>
</form>
