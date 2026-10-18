<script lang="ts">
	import { createMutation, createQuery, useQueryClient } from '@tanstack/svelte-query';
	import type { components } from '#lib/api/schema.js';
	import { apiRequest } from '#lib/api/client.js';
	import { apiErrorMessage } from '#lib/api/errors.js';
	import Pagination from '#lib/design/Pagination.svelte';
	import AdminNotices from '#lib/features/admin/AdminNotices.svelte';
	import AdminSectionState from '#lib/features/admin/AdminSectionState.svelte';
	import AdminUsers from '#lib/features/admin/AdminUsers.svelte';
	import { getAdminFilters } from '#lib/features/admin/filters.js';
	import { adminMutationOptions } from '#lib/features/admin/mutations.js';
	import { adminUsersQuery } from '#lib/features/admin/queries.js';
	import { msg, t, type MessageKey } from '#lib/i18n.js';

	type User = components['schemas']['AdminUserView'];

	let error = $state('');
	let notice = $state<MessageKey | null>(null);
	const { filters, setPage, setPageSize } = getAdminFilters();
	const users = createQuery(() => adminUsersQuery(filters(), true));
	const queryClient = useQueryClient();
	const adminMutation = createMutation(() =>
		adminMutationOptions('users', async () => {
			const { invalidateWorkspaces } = await import('#lib/query/invalidation.js');
			await Promise.all([
				queryClient.invalidateQueries({ queryKey: ['admin'] }),
				invalidateWorkspaces(queryClient)
			]);
		})
	);
	const busy = $derived(adminMutation.isPending);
	const pageCount = $derived(
		users.data?.total && users.data.limit
			? Math.max(1, Math.ceil(users.data.total / users.data.limit))
			: 1
	);
	$effect(() => {
		if (users.isFetching || !users.data) return;
		if (filters().page > pageCount) setPage(pageCount);
	});

	function mutate(operation: () => Promise<unknown>, success: MessageKey, form?: HTMLFormElement) {
		error = '';
		notice = null;
		void adminMutation
			.mutateAsync({ run: operation, form })
			.then(() => {
				notice = success;
			})
			.catch((reason) => {
				error = apiErrorMessage(reason, $t('Administration action failed'));
			});
	}

	function createUser(event: SubmitEvent) {
		event.preventDefault();
		const form = event.currentTarget as HTMLFormElement;
		const values = new FormData(form);
		void mutate(
			() =>
				apiRequest('POST', '/admin/users', {
					body: {
						username: String(values.get('username') ?? ''),
						password: String(values.get('password') ?? ''),
						role: values.get('role') === 'administrator' ? 'administrator' : 'member'
					}
				}),
			msg('User created'),
			form
		);
	}

	function updateUserStatus(user: User) {
		void mutate(
			() =>
				apiRequest('PUT', '/admin/users/{user_id}/status', {
					params: { path: { user_id: user.id } },
					body: { active: !user.active }
				}),
			user.active ? msg('User disabled') : msg('User enabled')
		);
	}

	function updateUserRole(event: SubmitEvent, userId: string) {
		event.preventDefault();
		const values = new FormData(event.currentTarget as HTMLFormElement);
		void mutate(
			() =>
				apiRequest('PUT', '/admin/users/{user_id}/role', {
					params: { path: { user_id: userId } },
					body: { role: values.get('role') === 'administrator' ? 'administrator' : 'member' }
				}),
			msg('User role saved')
		);
	}

	function resetUserPassword(event: SubmitEvent, userId: string) {
		event.preventDefault();
		const form = event.currentTarget as HTMLFormElement;
		const values = new FormData(form);
		void mutate(
			() =>
				apiRequest('PUT', '/admin/users/{user_id}/password', {
					params: { path: { user_id: userId } },
					body: { password: String(values.get('password') ?? '') }
				}),
			msg('User password reset'),
			form
		);
	}

	function revokeUserSessions(userId: string) {
		void mutate(
			() =>
				apiRequest('DELETE', '/admin/users/{user_id}/sessions', {
					params: { path: { user_id: userId } }
				}),
			msg('User sessions revoked')
		);
	}
</script>

<AdminNotices {error} {notice} />
<AdminSectionState loading={users.isPending} failed={users.isError} label={msg('Users')}>
	<AdminUsers
		users={users.data!}
		{busy}
		onCreateUser={createUser}
		onUpdateUserRole={updateUserRole}
		onUpdateUserStatus={updateUserStatus}
		onResetUserPassword={resetUserPassword}
		onRevokeUserSessions={revokeUserSessions}
	>
		{#snippet pagination()}
			<Pagination
				page={filters().page}
				{pageCount}
				pageSize={filters().pageSize}
				total={users.data?.total ?? 0}
				busy={users.isFetching || busy}
				onPageSize={setPageSize}
				label={$t('Administration pages')}
				onPage={setPage}
			/>
		{/snippet}
	</AdminUsers>
</AdminSectionState>
