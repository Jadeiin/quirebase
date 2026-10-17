<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { components } from '#lib/api/schema.js';
	import Badge from '#lib/design/Badge.svelte';
	import Button from '#lib/design/Button.svelte';
	import ItemRow from '#lib/design/ItemRow.svelte';
	import Panel from '#lib/design/Panel.svelte';
	import SectionHeader from '#lib/design/SectionHeader.svelte';
	import { domainLabel } from '#lib/domain-labels.js';
	import { dateFormat } from '#lib/format.js';
	import { t } from '#lib/i18n.js';

	type User = components['schemas']['AdminUserView'];

	let {
		users,
		busy,
		pagination,
		onCreateUser,
		onUpdateUserRole,
		onUpdateUserStatus,
		onResetUserPassword,
		onRevokeUserSessions
	}: {
		users: components['schemas']['AdminUsersView'];
		busy: boolean;
		pagination: Snippet;
		onCreateUser: (event: SubmitEvent) => void;
		onUpdateUserRole: (event: SubmitEvent, userId: string) => void;
		onUpdateUserStatus: (user: User) => void;
		onResetUserPassword: (event: SubmitEvent, userId: string) => void;
		onRevokeUserSessions: (userId: string) => void;
	} = $props();
	let createOpen = $state(false);
</script>

<SectionHeader spacing="compact">
	<div>
		<h2>{$t('Users')} <span class="text-surface-600-400">({users.total})</span></h2>
		<p class="text-sm text-surface-600-400">{$t('Manage accounts, roles, and sign-in access.')}</p>
	</div>
	{#snippet actions()}
		<Button
			variant="filled"
			disabled={busy}
			aria-expanded={createOpen}
			onclick={() => (createOpen = !createOpen)}>{$t('Create user')}</Button
		>
	{/snippet}
</SectionHeader>

{#if createOpen}
	<Panel as="form" class="mb-4 grid grid-cols-1 gap-3" onsubmit={onCreateUser}>
		<h3>{$t('Create user')}</h3>
		<div class="grid grid-cols-1 gap-3 sm:grid-cols-3">
			<label>{$t('Username')}<input class="input" name="username" maxlength="120" required /></label
			>
			<label
				>{$t('Password')}<input
					class="input"
					name="password"
					type="password"
					autocomplete="new-password"
					minlength="12"
					required
				/></label
			>
			<label
				>{$t('Role')}<select class="select" name="role">
					<option value="member">{$t('Member')}</option>
					<option value="administrator">{$t('Administrator')}</option>
				</select></label
			>
		</div>
		<div class="flex flex-wrap gap-2">
			<Button variant="filled" disabled={busy}>{$t('Create user')}</Button>
			<Button type="button" disabled={busy} onclick={() => (createOpen = false)}
				>{$t('Cancel')}</Button
			>
		</div>
	</Panel>
{/if}

<Panel>
	{#each users.items as user (user.id)}
		<ItemRow as="article" aria-label={user.username}>
			<div class="flex flex-wrap items-start justify-between gap-3">
				<div class="min-w-0">
					<strong class="break-words">{user.username}</strong>
					<p class="text-sm text-surface-600-400">
						{$t(domainLabel(user.role))} · {$t('Created')}
						{$dateFormat.format(new Date(user.created_at))}
					</p>
				</div>
				<Badge variant={user.active ? 'success' : 'surface'}
					>{user.active ? $t('Active') : $t('Disabled')}</Badge
				>
			</div>
			<details class="mt-2">
				<summary class="cursor-pointer text-sm font-medium text-primary-700-300"
					>{$t('Manage user')}</summary
				>
				<div class="mt-4 grid grid-cols-1 gap-4">
					<form
						class="flex flex-wrap items-end gap-2"
						onsubmit={(event) => onUpdateUserRole(event, user.id)}
					>
						<label class="min-w-36"
							>{$t('Role for {username}', { username: user.username })}
							<select class="select" name="role" value={user.role}>
								<option value="member">{$t('Member')}</option>
								<option value="administrator">{$t('Administrator')}</option>
							</select>
						</label>
						<Button disabled={busy}>{$t('Save role')}</Button>
					</form>
					<form
						class="flex flex-wrap items-end gap-2"
						onsubmit={(event) => onResetUserPassword(event, user.id)}
					>
						<label class="min-w-0 grow sm:max-w-sm"
							>{$t('New password for {username}', { username: user.username })}
							<input
								class="input"
								name="password"
								type="password"
								autocomplete="new-password"
								minlength="12"
								required
							/>
						</label>
						<Button disabled={busy}>{$t('Reset password')}</Button>
					</form>
					<p class="text-sm text-surface-600-400">
						{$t(
							'Disabling a user immediately blocks account access and ends sign-in sessions. Workspace ownership is retained; reassign it separately in Workspace governance.'
						)}
					</p>
					<div class="flex flex-wrap gap-2 border-t border-surface-300-700 pt-3">
						<Button disabled={busy} onclick={() => onRevokeUserSessions(user.id)}
							>{$t('Revoke sessions')}</Button
						>
						<Button disabled={busy} onclick={() => onUpdateUserStatus(user)}
							>{user.active ? $t('Disable user') : $t('Enable user')}</Button
						>
					</div>
				</div>
			</details>
		</ItemRow>
	{:else}
		<p class="py-6 text-surface-600-400">{$t('No users.')}</p>
	{/each}
	{@render pagination()}
</Panel>
