<script lang="ts">
	import Panel from '$lib/design/Panel.svelte';
	import Notice from '$lib/design/Notice.svelte';
	import { domainLabel } from '$lib/domain-labels';
	import { t } from '$lib/i18n';
	import type { components } from '$lib/api/schema';
	import Button from '$lib/design/Button.svelte';
	import ItemRow from '$lib/design/ItemRow.svelte';

	type User = components['schemas']['AdminUserView'];
	type Users = components['schemas']['AdminUsersView'];

	let {
		users,
		busy,
		invitationUrl,
		onCreateUser,
		onCreateInvitation,
		onUpdateUserRole,
		onUpdateUserStatus,
		onResetUserPassword,
		onRevokeUserSessions
	} = $props<{
		users: Users;
		busy: boolean;
		invitationUrl: string;
		onCreateUser: (event: SubmitEvent) => void;
		onCreateInvitation: (event: SubmitEvent) => void;
		onUpdateUserRole: (event: SubmitEvent, userId: string) => void;
		onUpdateUserStatus: (user: User) => void;
		onResetUserPassword: (event: SubmitEvent, userId: string) => void;
		onRevokeUserSessions: (userId: string) => void;
	}>();
</script>

<div class="grid grid-cols-1 gap-4 min-[800px]:grid-cols-[minmax(0,2fr)_minmax(16rem,1fr)]">
	<Panel class="mt-4">
		<h2>{$t('Users')} ({users.total})</h2>
		{#each users.users as user (user.id)}
			<ItemRow>
				<div class="grid grid-cols-1 gap-1">
					<strong>{user.username}</strong><span class="text-surface-600-400"
						>{$t(domainLabel(user.role))} · {user.active ? $t('active') : $t('disabled')}</span
					>
				</div>
				<div class="flex flex-wrap items-center gap-2">
					<form class="flex flex-wrap gap-2" onsubmit={(event) => onUpdateUserRole(event, user.id)}>
						<label
							><span class="sr-only">{$t('Role for {username}', { username: user.username })}</span
							><select class="input w-auto min-w-36" name="role" value={user.role}
								><option value="member">{$t('Member')}</option><option value="administrator"
									>{$t('Administrator')}</option
								></select
							></label
						><Button disabled={busy}>{$t('Save role')}</Button>
					</form>
					<Button disabled={busy} onclick={() => onUpdateUserStatus(user)}
						>{user.active ? $t('Disable user') : $t('Enable user')}</Button
					>
					<form
						class="flex flex-wrap gap-2"
						onsubmit={(event) => onResetUserPassword(event, user.id)}
					>
						<label
							><span class="sr-only"
								>{$t('New password for {username}', { username: user.username })}</span
							><input
								class="input w-auto min-w-36"
								name="password"
								type="password"
								autocomplete="new-password"
								minlength="12"
								placeholder={$t('New password')}
								required
							/></label
						><Button disabled={busy}>{$t('Reset password')}</Button>
					</form>
					<Button disabled={busy} onclick={() => onRevokeUserSessions(user.id)}
						>{$t('Revoke sessions')}</Button
					>
				</div>
			</ItemRow>
		{:else}
			<p class="text-surface-600-400">{$t('No users.')}</p>
		{/each}
		<h2>{$t('Invitations')}</h2>
		{#each users.invitations as invitation (invitation.id)}
			<ItemRow>
				<strong>{invitation.username}</strong><span class="text-surface-600-400"
					>{$t(domainLabel(invitation.role))} · {invitation.accepted_at
						? $t('accepted')
						: $t('pending')}</span
				>
			</ItemRow>
		{:else}
			<p class="text-surface-600-400">{$t('No invitations.')}</p>
		{/each}
	</Panel>
	<aside class="grid grid-cols-1 gap-3">
		<Panel as="form" class="grid grid-cols-1 gap-3" onsubmit={onCreateUser}>
			<h2>{$t('Create user')}</h2>
			<input class="input" name="username" placeholder={$t('Username')} required /><input
				class="input"
				name="password"
				type="password"
				minlength="12"
				placeholder={$t('Password')}
				required
			/><select class="select" name="role"
				><option value="member">{$t('Member')}</option><option value="administrator"
					>{$t('Administrator')}</option
				></select
			><Button disabled={busy}>{$t('Create user')}</Button>
		</Panel>
		<Panel as="form" class="grid grid-cols-1 gap-3" onsubmit={onCreateInvitation}>
			<h2>{$t('Invite user')}</h2>
			<input class="input" name="username" placeholder={$t('Username')} required /><select
				class="select"
				name="role"
				><option value="member">{$t('Member')}</option><option value="administrator"
					>{$t('Administrator')}</option
				></select
			><Button disabled={busy}>{$t('Create invitation')}</Button>
			{#if invitationUrl}
				<Notice as="div" variant="warning" class="grid grid-cols-1 gap-2 [overflow-wrap:anywhere]">
					<strong>{$t('Copy this invitation URL now')}</strong><a
						href={invitationUrl}
						rel="external">{invitationUrl}</a
					>
				</Notice>
			{/if}
		</Panel>
	</aside>
</div>
