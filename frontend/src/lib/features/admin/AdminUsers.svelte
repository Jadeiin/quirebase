<script lang="ts">
	import type { Snippet } from 'svelte';
	import { SvelteSet } from 'svelte/reactivity';
	import type { components } from '#lib/api/schema.js';
	import Badge from '#lib/design/Badge.svelte';
	import Button from '#lib/design/Button.svelte';
	import DataTable from '#lib/design/DataTable.svelte';
	import Icon from '#lib/design/Icon.svelte';
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
		onRefresh,
		onCreateUser,
		onUpdateUserRole,
		onUpdateUserStatus,
		onResetUserPassword,
		onRevokeUserSessions
	}: {
		users: components['schemas']['AdminUsersView'];
		busy: boolean;
		pagination: Snippet;
		onRefresh: () => void;
		onCreateUser: (event: SubmitEvent) => void;
		onUpdateUserRole: (event: SubmitEvent, userId: string) => void;
		onUpdateUserStatus: (user: User) => void;
		onResetUserPassword: (event: SubmitEvent, userId: string) => void;
		onRevokeUserSessions: (userId: string) => void;
	} = $props();
	let createOpen = $state(false);
	const expandedUsers = new SvelteSet<string>();

	function toggleUser(userId: string) {
		if (expandedUsers.has(userId)) expandedUsers.delete(userId);
		else expandedUsers.add(userId);
	}
</script>

<SectionHeader spacing="compact">
	<div>
		<h2>{$t('Users')} <span class="text-surface-600-400">({users.total})</span></h2>
		<p class="text-sm text-surface-600-400">{$t('Manage accounts, roles, and sign-in access.')}</p>
	</div>
	{#snippet actions()}
		<Button type="button" disabled={busy} onclick={onRefresh}>{$t('Refresh')}</Button>
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
			<label
				>{$t('Username')}<input
					disabled={busy}
					class="input"
					name="username"
					maxlength="120"
					required
				/></label
			>
			<label
				>{$t('Password')}<input
					disabled={busy}
					class="input"
					name="password"
					type="password"
					autocomplete="new-password"
					minlength="12"
					required
				/></label
			>
			<label
				>{$t('Role')}<select disabled={busy} class="select" name="role">
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

<Panel padding="none">
	{#if users.items.length}
		<DataTable label={$t('Users')}>
			<thead>
				<tr>
					<th scope="col">{$t('Username')}</th>
					<th scope="col">{$t('Role')}</th>
					<th scope="col">{$t('Status')}</th>
					<th scope="col">{$t('Created')}</th>
					<th scope="col">{$t('Actions')}</th>
				</tr>
			</thead>
			{#each users.items as user (user.id)}
				<tbody aria-label={user.username}>
					<tr>
						<th scope="row" class="font-semibold">{user.username}</th>
						<td data-label={$t('Role')}>{$t(domainLabel(user.role))}</td>
						<td data-label={$t('Status')}>
							<Badge variant={user.active ? 'success' : 'surface'}
								>{user.active ? $t('Active') : $t('Disabled')}</Badge
							>
						</td>
						<td data-label={$t('Created')}>
							<time datetime={user.created_at}>{$dateFormat.format(new Date(user.created_at))}</time
							>
						</td>
						<td data-label={$t('Actions')}>
							<Button
								type="button"
								size="sm"
								disabled={busy}
								aria-expanded={expandedUsers.has(user.id)}
								aria-controls={`admin-user-manage-${user.id}`}
								onclick={() => toggleUser(user.id)}
								>{$t('Manage user')}<span class:rotate-180={expandedUsers.has(user.id)}
									><Icon name="chevron-down" size={14} /></span
								></Button
							>
						</td>
					</tr>
					<tr hidden={!expandedUsers.has(user.id)}>
						<td colspan="5" class="bg-surface-100-900">
							<div id={`admin-user-manage-${user.id}`} class="grid grid-cols-1 gap-4 py-2">
								<form
									class="flex flex-wrap items-end gap-2"
									onsubmit={(event) => onUpdateUserRole(event, user.id)}
								>
									<label class="min-w-36"
										>{$t('Role for {username}', { username: user.username })}
										<select disabled={busy} class="select" name="role" value={user.role}>
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
											disabled={busy}
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
										'Disabling a user ends all sessions and blocks access. Workspace ownership stays assigned; reassign it in Workspace management.'
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
						</td>
					</tr>
				</tbody>
			{/each}
		</DataTable>
	{:else}
		<p class="px-5 py-6 text-surface-600-400">{$t('No users.')}</p>
	{/if}
	{@render pagination()}
</Panel>
