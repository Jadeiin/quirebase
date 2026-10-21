<script lang="ts">
	import { createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { ApiError, apiRequest } from '#lib/api/client.js';
	import { apiErrorMessage } from '#lib/api/errors.js';
	import type { components } from '#lib/api/schema.js';
	import Button from '#lib/design/Button.svelte';
	import Notice from '#lib/design/Notice.svelte';
	import Panel from '#lib/design/Panel.svelte';
	import QueryError from '#lib/design/QueryError.svelte';
	import SearchSelect from '#lib/design/SearchSelect.svelte';
	import { readAdminFilters } from './list-state';
	import { adminUsersQuery, adminWorkspaceQuery } from '#lib/features/admin/queries.js';
	import { isAdminUnavailableError } from './read-state.js';
	import { invalidateWorkspaces } from '#lib/query/invalidation.js';
	import { t } from '#lib/i18n.js';

	let {
		workspace,
		onClose,
		onError
	}: {
		workspace: components['schemas']['AdminWorkspaceView'];
		onClose: () => void;
		onError: (message: string) => void;
	} = $props();
	const queryClient = useQueryClient();
	let search = $state<string | null>(null);
	let receiverId = $state('');
	let selectedUser = $state<components['schemas']['AdminUserView']>();
	let reason = $state('');
	let busy = $state(false);
	const detail = createQuery(() => adminWorkspaceQuery(workspace.id));
	const unavailable = $derived(detail.data === null || isAdminUnavailableError(detail.error));
	// Only an uninitialized read may fall back to the selected row, never an access-loss tombstone.
	const current = $derived(unavailable ? undefined : (detail.data ?? workspace));
	const users = createQuery(() =>
		adminUsersQuery(
			{
				...readAdminFilters(new URLSearchParams(), 'users'),
				search: search ?? '',
				active: 'true'
			},
			!unavailable
		)
	);

	function selectReceiver(userId: string) {
		selectedUser =
			users.data?.items.find((user) => user.id === userId) ??
			(selectedUser?.id === userId ? selectedUser : undefined);
		receiverId = userId;
	}
	async function reassign(event: SubmitEvent) {
		event.preventDefault();
		const target = current;
		if (
			busy ||
			!target ||
			!receiverId ||
			receiverId === target.owner_id ||
			reason.trim().length < 10 ||
			!target.can_reassign_owner
		)
			return;
		// Keep completion callbacks bound to this submission even if its keyed form is replaced.
		const close = onClose;
		const reportError = onError;
		busy = true;
		reportError('');
		try {
			await apiRequest('POST', '/admin/workspaces/{workspace_id}/owner', {
				params: { path: { workspace_id: target.id } },
				body: {
					new_owner_user_id: receiverId,
					expected_owner_user_id: target.owner_id,
					reason: reason.trim()
				}
			});
			await Promise.all([
				queryClient.invalidateQueries({ queryKey: ['admin'] }),
				invalidateWorkspaces(queryClient)
			]);
			close();
		} catch (failure) {
			if (failure instanceof ApiError && failure.code === 'version_conflict') {
				reportError(
					$t(
						'Ownership changed. Review the refreshed owner and submit again. Your draft is preserved.'
					)
				);
				await queryClient.invalidateQueries({ queryKey: ['admin', 'workspaces'] });
			} else reportError(apiErrorMessage(failure, $t('Workspace governance action failed')));
		} finally {
			busy = false;
		}
	}
</script>

<Panel class="min-w-0">
	{#if detail.isError || detail.data === null}
		<QueryError
			message={apiErrorMessage(detail.error, $t('Unable to load workspaces.'))}
			busy={detail.isFetching}
			onRetry={() => void detail.refetch()}
		/>
	{/if}
	{#if current}
		<form
			aria-label={$t('Reassign owner for {workspace}', { workspace: current.name })}
			class="grid w-full min-w-0 grid-cols-1 gap-3"
			onsubmit={reassign}
		>
			<h3 class="font-semibold">
				{$t('Reassign owner for {workspace}', { workspace: current.name })}
			</h3>
			<p class="text-xs break-all text-surface-600-400">{current.id}</p>
			<p class="text-sm text-surface-600-400">
				{$t(
					'The selected user gains Workspace owner access. The previous owner becomes a Workspace admin. This does not disable the previous account.'
				)}
			</p>
			<p class="text-sm">{$t('Current owner: {username}', { username: current.owner_username })}</p>
			{#if !current.can_reassign_owner}<Notice
					>{$t('Owner reassignment is currently unavailable for this Workspace.')}</Notice
				>{/if}
			{#if users.isError || users.data === null}<QueryError
					message={apiErrorMessage(users.error, $t('Failed to load users'))}
					busy={users.isFetching}
					onRetry={() => void users.refetch()}
				/>{/if}
			<SearchSelect
				label={$t('New owner')}
				emptyLabel={$t('Search active users')}
				bind:value={() => receiverId, selectReceiver}
				bind:search
				selectedLabel={selectedUser?.id === receiverId ? selectedUser.username : undefined}
				options={(users.data?.items ?? []).map((user) => ({
					value: user.id,
					label: user.username
				}))}
				filterOptions={false}
				loading={users.isFetching}
				disabled={busy || !current.can_reassign_owner}
				required
			/>
			<p class="text-xs text-surface-600-400">
				{$t('Showing up to 20 active users. Type to narrow the search.')}
			</p>
			<label class="grid grid-cols-1 gap-1"
				>{$t('Reason (at least 10 characters)')}
				<textarea
					class="input"
					bind:value={reason}
					minlength="10"
					maxlength="1000"
					disabled={busy || !current.can_reassign_owner}
					required></textarea>
			</label>
			<div class="flex flex-wrap gap-2">
				<Button
					variant="filled"
					disabled={busy ||
						!current.can_reassign_owner ||
						!receiverId ||
						receiverId === current.owner_id ||
						reason.trim().length < 10}>{$t('Confirm owner reassignment')}</Button
				>
				<Button type="button" disabled={busy} onclick={onClose}>{$t('Cancel')}</Button>
			</div>
		</form>
	{:else}<Button type="button" onclick={onClose}>{$t('Cancel')}</Button>{/if}
</Panel>
