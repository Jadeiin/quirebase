<script lang="ts">
	import { domainLabel } from '$lib/domain-labels';
	import { t } from '$lib/i18n';
	import type { components } from '$lib/api/schema';

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

<div class="item-layout">
	<section class="list-panel card border border-surface-300-700 bg-surface-50-950 p-5 shadow-sm">
		<h2>{$t('Users')} ({users.total})</h2>
		{#each users.users as user (user.id)}
			<div class="item-row admin-user-row">
				<div>
					<strong>{user.username}</strong><span class="text-surface-600-400"
						>{$t(domainLabel(user.role))} · {user.active ? $t('active') : $t('disabled')}</span
					>
				</div>
				<div class="admin-user-actions">
					<form class="toolbar" onsubmit={(event) => onUpdateUserRole(event, user.id)}>
						<label
							><span class="sr-only">{$t('Role for')} {user.username}</span><select
								class="compact input"
								name="role"
								value={user.role}
								><option value="member">{$t('Member')}</option><option value="administrator"
									>{$t('Administrator')}</option
								></select
							></label
						><button class="btn preset-tonal-surface font-semibold" disabled={busy}
							>{$t('Save role')}</button
						>
					</form>
					<button
						class="btn preset-tonal-surface font-semibold"
						disabled={busy}
						onclick={() => onUpdateUserStatus(user)}
						>{user.active ? $t('Disable user') : $t('Enable user')}</button
					>
					<form class="toolbar" onsubmit={(event) => onResetUserPassword(event, user.id)}>
						<label
							><span class="sr-only">{$t('New password for')} {user.username}</span><input
								class="compact input"
								name="password"
								type="password"
								autocomplete="new-password"
								minlength="12"
								placeholder={$t('New password')}
								required
							/></label
						><button class="btn preset-tonal-surface font-semibold" disabled={busy}
							>{$t('Reset password')}</button
						>
					</form>
					<button
						class="btn preset-tonal-surface font-semibold"
						disabled={busy}
						onclick={() => onRevokeUserSessions(user.id)}>{$t('Revoke sessions')}</button
					>
				</div>
			</div>
		{:else}
			<p class="text-surface-600-400">{$t('No users.')}</p>
		{/each}
		<h2>{$t('Invitations')}</h2>
		{#each users.invitations as invitation (invitation.id)}
			<div class="item-row">
				<strong>{invitation.username}</strong><span class="text-surface-600-400"
					>{$t(domainLabel(invitation.role))} · {invitation.accepted_at
						? $t('accepted')
						: $t('pending')}</span
				>
			</div>
		{:else}
			<p class="text-surface-600-400">{$t('No invitations.')}</p>
		{/each}
	</section>
	<aside class="stack">
		<form
			class="stack card border border-surface-300-700 bg-surface-50-950 p-5 shadow-sm"
			onsubmit={onCreateUser}
		>
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
			><button class="btn preset-tonal-surface font-semibold" disabled={busy}
				>{$t('Create user')}</button
			>
		</form>
		<form
			class="stack card border border-surface-300-700 bg-surface-50-950 p-5 shadow-sm"
			onsubmit={onCreateInvitation}
		>
			<h2>{$t('Invite user')}</h2>
			<input class="input" name="username" placeholder={$t('Username')} required /><select
				class="select"
				name="role"
				><option value="member">{$t('Member')}</option><option value="administrator"
					>{$t('Administrator')}</option
				></select
			><button class="btn preset-tonal-surface font-semibold" disabled={busy}
				>{$t('Create invitation')}</button
			>
			{#if invitationUrl}
				<div class="secret" role="status">
					<strong>{$t('Copy this invitation URL now')}</strong><a
						href={invitationUrl}
						rel="external">{invitationUrl}</a
					>
				</div>
			{/if}
		</form>
	</aside>
</div>
