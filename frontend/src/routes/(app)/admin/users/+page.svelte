<script lang="ts">
	import { createMutation, createQuery } from '@tanstack/svelte-query';
	import type { components } from '$lib/api/schema';
	import { apiRequest } from '$lib/api/client';
	import { apiErrorMessage } from '$lib/api/errors';
	import Pagination from '$lib/design/Pagination.svelte';
	import AdminNotices from '$lib/features/admin/AdminNotices.svelte';
	import AdminSectionState from '$lib/features/admin/AdminSectionState.svelte';
	import AdminUsers from '$lib/features/admin/AdminUsers.svelte';
	import { getAdminFilters } from '$lib/features/admin/filters';
	import { adminMutationOptions } from '$lib/features/admin/mutations';
	import { adminUsersQuery } from '$lib/features/admin/queries';
	import { msg, t, type MessageKey } from '$lib/i18n';

	type User = components['schemas']['AdminUserView'];
	type InvitationCreated = components['schemas']['AdminInvitationCreatedView'];

	let error = $state('');
	let notice = $state<MessageKey | null>(null);
	let invitationUrl = $state('');
	const { filters, setPage } = getAdminFilters();
	const users = createQuery(() => adminUsersQuery(filters(), true));
	const adminMutation = createMutation(() => adminMutationOptions('users', () => users.refetch()));
	const busy = $derived(adminMutation.isPending);
	const pageCount = $derived(
		users.data?.total && users.data.per_page
			? Math.max(1, Math.ceil(users.data.total / users.data.per_page))
			: 1
	);

	function mutate(
		operation: () => Promise<unknown>,
		success: MessageKey,
		form?: HTMLFormElement,
		onSuccess?: (result: unknown) => void
	) {
		error = '';
		notice = null;
		void adminMutation
			.mutateAsync({ run: operation, form })
			.then((result) => {
				onSuccess?.(result);
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

	function createInvitation(event: SubmitEvent) {
		event.preventDefault();
		const form = event.currentTarget as HTMLFormElement;
		const values = new FormData(form);
		invitationUrl = '';
		void mutate(
			() =>
				apiRequest('POST', '/admin/invitations', {
					body: {
						username: String(values.get('username') ?? ''),
						role: values.get('role') === 'administrator' ? 'administrator' : 'member'
					}
				}),
			msg('Invitation created'),
			form,
			(result) => {
				const invitation = result as InvitationCreated;
				invitationUrl = new URL(invitation.accept_path, window.location.origin).href;
			}
		);
	}
</script>

<AdminNotices {error} {notice} />
<AdminSectionState loading={users.isPending} failed={users.isError} label={msg('Users')}>
	<AdminUsers
		users={users.data!}
		{busy}
		{invitationUrl}
		onCreateUser={createUser}
		onCreateInvitation={createInvitation}
		onUpdateUserRole={updateUserRole}
		onUpdateUserStatus={updateUserStatus}
		onResetUserPassword={resetUserPassword}
		onRevokeUserSessions={revokeUserSessions}
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
