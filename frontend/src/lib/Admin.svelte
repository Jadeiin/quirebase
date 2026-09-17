<script lang="ts">
	import { resolve } from '$app/paths';
	import { createQuery } from '@tanstack/svelte-query';
	import { SvelteURLSearchParams } from 'svelte/reactivity';
	import { apiRequest, type ItemSummary } from '$lib/api/client';
	import RichText from '$lib/design/RichText.svelte';
	import { domainLabel } from '$lib/domain-labels';
	import { msg, t, type MessageKey } from '$lib/i18n';
	import type { components } from '$lib/api/schema';

	type Overview = components['schemas']['AdminOverviewView'];
	type User = components['schemas']['AdminUserView'];
	type Users = components['schemas']['AdminUsersView'];
	type Project = components['schemas']['AdminProjectItemView'];
	type AuditEvent = components['schemas']['AdminAuditEventView'];
	type Workflow = components['schemas']['WorkflowSummaryView'];
	type Settings = components['schemas']['AdminSettingsView'];
	type CreatedInvitation = components['schemas']['AdminInvitationCreatedView'];

	type AdminSection =
		| 'overview'
		| 'users'
		| 'projects'
		| 'items'
		| 'audit'
		| 'workflows'
		| 'settings'
		| 'maintenance';

	let { section } = $props<{ section: AdminSection }>();
	let error = $state('');
	let notice = $state<MessageKey | null>(null);
	let busy = $state(false);
	let invitationUrl = $state('');
	let adminPage = $state(1);
	let searchInput = $state('');
	let appliedSearch = $state('');
	let filterA = $state('');
	let appliedFilterA = $state('');
	let filterB = $state('');
	let appliedFilterB = $state('');
	let activeSection = $state<AdminSection | null>(null);
	const labels: Record<AdminSection, MessageKey> = {
		overview: msg('Overview'),
		users: msg('Users'),
		projects: msg('Projects'),
		items: msg('Items'),
		audit: msg('Audit'),
		workflows: msg('Workflows'),
		settings: msg('Settings'),
		maintenance: msg('Maintenance')
	};
	function sectionPath(key: string) {
		return key === 'overview' ? ('/admin' as const) : (`/admin/${key}` as const);
	}
	const settingFields: ReadonlyArray<readonly [keyof Settings, MessageKey]> = [
		['metadata_contact_email', msg('Metadata contact email')],
		['ncbi_api_key', msg('NCBI API key')],
		['openalex_api_key', msg('OpenAlex API key')],
		['nasa_ads_token', msg('NASA ADS token')],
		['ieee_api_key', msg('IEEE API key')],
		['session_days', msg('Session lifetime in days')],
		['max_pdf_bytes', msg('Maximum PDF size in bytes')],
		['max_attachment_bytes', msg('Maximum attachment size in bytes')],
		['export_ttl_hours', msg('Export lifetime in hours')]
	] as const;

	const maintenanceOperations = [
		['reindex_all', msg('Reindex all Items')],
		['check_objects', msg('Check stored objects')],
		['backup', msg('Create backup')],
		['recommend_tags_all', msg('Recommend Tags for all Items')]
	] as const;
	const sectionLabel = $derived(labels[section as AdminSection]);
	const queryString = $derived.by(() => {
		const parameters = new SvelteURLSearchParams();
		if (adminPage > 1) parameters.set('page', String(adminPage));
		if (appliedSearch) parameters.set('search', appliedSearch);
		if (section === 'users') {
			if (appliedFilterA) parameters.set('role', appliedFilterA);
			if (appliedFilterB) parameters.set('active', appliedFilterB);
		} else if (section === 'projects') {
			if (appliedFilterA) parameters.set('state', appliedFilterA);
			if (appliedFilterB) parameters.set('visibility', appliedFilterB);
		} else if (section === 'items') {
			if (appliedFilterA) parameters.set('has_pdf', appliedFilterA);
		} else if (section === 'audit') {
			if (appliedFilterA) parameters.set('action', appliedFilterA);
			if (appliedFilterB) parameters.set('target_type', appliedFilterB);
		} else if (section === 'workflows' && appliedFilterA) {
			parameters.set('state', appliedFilterA);
		}
		return parameters.toString();
	});
	const data = createQuery(() => ({
		queryKey: ['admin', section, queryString],
		queryFn: () => apiRequest<unknown>(`/admin/${section}${queryString ? `?${queryString}` : ''}`)
	}));
	const pagination = $derived(
		data.data as { total?: number; page?: number; per_page?: number } | undefined
	);
	const pageCount = $derived(
		pagination?.total && pagination.per_page
			? Math.max(1, Math.ceil(pagination.total / pagination.per_page))
			: 1
	);

	$effect(() => {
		if (activeSection === null) {
			activeSection = section;
			return;
		}
		if (section === activeSection) return;
		activeSection = section;
		searchInput = '';
		appliedSearch = '';
		filterA = '';
		appliedFilterA = '';
		filterB = '';
		appliedFilterB = '';
		adminPage = 1;
	});

	function applyFilters(event: SubmitEvent) {
		event.preventDefault();
		adminPage = 1;
		appliedSearch = searchInput.trim();
		appliedFilterA = filterA;
		appliedFilterB = filterB;
	}

	function clearFilters() {
		searchInput = '';
		filterA = '';
		filterB = '';
		appliedSearch = '';
		appliedFilterA = '';
		appliedFilterB = '';
		adminPage = 1;
	}

	async function mutate(
		operation: () => Promise<unknown>,
		success: MessageKey,
		form?: HTMLFormElement
	) {
		busy = true;
		error = '';
		notice = null;
		try {
			await operation();
			await data.refetch();
			form?.reset();
			notice = success;
		} catch (reason) {
			error = reason instanceof Error ? reason.message : $t('Administration action failed');
		} finally {
			busy = false;
		}
	}

	function createUser(event: SubmitEvent) {
		event.preventDefault();
		const form = event.currentTarget as HTMLFormElement;
		const values = new FormData(form);
		void mutate(
			() =>
				apiRequest('/admin/users', {
					method: 'POST',
					body: {
						username: values.get('username'),
						password: values.get('password'),
						role: values.get('role')
					}
				}),
			msg('User created'),
			form
		);
	}

	function updateUserStatus(user: User) {
		void mutate(
			() =>
				apiRequest(`/admin/users/${user.id}/status`, {
					method: 'PUT',
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
				apiRequest(`/admin/users/${userId}/role`, {
					method: 'PUT',
					body: { role: values.get('role') }
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
				apiRequest(`/admin/users/${userId}/password`, {
					method: 'PUT',
					body: { password: values.get('password') }
				}),
			msg('User password reset'),
			form
		);
	}

	function revokeUserSessions(userId: string) {
		void mutate(
			() => apiRequest(`/admin/users/${userId}/sessions`, { method: 'DELETE' }),
			msg('User sessions revoked')
		);
	}

	async function createInvitation(event: SubmitEvent) {
		event.preventDefault();
		const form = event.currentTarget as HTMLFormElement;
		const values = new FormData(form);
		busy = true;
		error = '';
		notice = null;
		invitationUrl = '';
		try {
			const invitation = await apiRequest<CreatedInvitation>('/admin/invitations', {
				method: 'POST',
				body: { username: values.get('username'), role: values.get('role') }
			});
			invitationUrl = new URL(invitation.accept_path, window.location.origin).href;
			await data.refetch();
			form.reset();
			notice = msg('Invitation created');
		} catch (reason) {
			error = reason instanceof Error ? reason.message : $t('Administration action failed');
		} finally {
			busy = false;
		}
	}

	function saveSettings(event: SubmitEvent) {
		event.preventDefault();
		const form = event.currentTarget as HTMLFormElement;
		const values: Record<string, FormDataEntryValue | number> = Object.fromEntries(
			new FormData(form)
		);
		for (const key of ['session_days', 'max_pdf_bytes', 'max_attachment_bytes', 'export_ttl_hours'])
			values[key] = Number(values[key]);
		void mutate(
			() => apiRequest('/admin/settings', { method: 'PUT', body: values }),
			msg('Settings saved')
		);
	}

	async function runMaintenance(operation: string) {
		busy = true;
		error = '';
		notice = msg('Maintenance operation started');
		try {
			const started = await apiRequest<{ id: string }>(`/admin/maintenance/${operation}`, {
				method: 'POST'
			});
			for (;;) {
				const workflow = await apiRequest<Workflow>(`/admin/workflows/${started.id}`);
				if (workflow.state === 'succeeded') break;
				if (workflow.state === 'failed' || workflow.state === 'cancelled') {
					throw new Error(workflow.error || $t('Maintenance operation failed'));
				}
				await new Promise((resolveDelay) => window.setTimeout(resolveDelay, 750));
			}
			await data.refetch();
			notice = msg('Maintenance operation completed');
		} catch (reason) {
			error = reason instanceof Error ? reason.message : $t('Maintenance operation failed');
		} finally {
			busy = false;
		}
	}

	function deleteAdminItem(itemId: string) {
		if (!window.confirm($t('Permanently delete this Item?'))) return;
		void mutate(
			() => apiRequest(`/admin/items/${itemId}`, { method: 'DELETE' }),
			msg('Item deleted')
		);
	}

	function downloadBackup(workflowId: string) {
		location.assign(`/api/v1/admin/maintenance/backups/${workflowId}/content`);
	}
</script>

<div class="workspace-header">
	<div>
		<h1>{$t('Administration')}</h1>
		<p class="text-surface-600">{$t('Users, storage, audit, settings, and durable operations.')}</p>
	</div>
</div>
<nav class="tabs" aria-label={$t('Administration sections')}>
	{#each Object.entries(labels) as [key, label] (key)}<a
			aria-current={section === key ? 'page' : undefined}
			href={resolve(sectionPath(key))}>{$t(label)}</a
		>{/each}
</nav>
{#if ['users', 'projects', 'items', 'audit', 'workflows'].includes(section)}
	<form
		class="toolbar mb-4 items-end card border border-surface-300 bg-surface-50 p-5 shadow-sm"
		onsubmit={applyFilters}
	>
		{#if section !== 'workflows'}
			<label class="grow">{$t('Search')}<input class="input" bind:value={searchInput} /></label>
		{/if}
		{#if section === 'users'}
			<label
				>{$t('Role')}<select class="compact input" bind:value={filterA}
					><option value="">{$t('All roles')}</option><option value="member">{$t('Member')}</option
					><option value="administrator">{$t('Administrator')}</option></select
				></label
			>
			<label
				>{$t('Status')}<select class="compact input" bind:value={filterB}
					><option value="">{$t('Any status')}</option><option value="true">{$t('Active')}</option
					><option value="false">{$t('Disabled')}</option></select
				></label
			>
		{:else if section === 'projects'}
			<label
				>{$t('State')}<select class="compact input" bind:value={filterA}
					><option value="">{$t('Any state')}</option><option value="active">{$t('Active')}</option
					><option value="archived">{$t('Archived')}</option></select
				></label
			>
			<label
				>{$t('Visibility')}<select class="compact input" bind:value={filterB}
					><option value="">{$t('Any visibility')}</option><option value="private"
						>{$t('Private')}</option
					><option value="public">{$t('Public')}</option></select
				></label
			>
		{:else if section === 'items'}
			<label
				>{$t('PDF availability')}<select class="compact input" bind:value={filterA}
					><option value="">{$t('Any')}</option><option value="true">{$t('Has PDF')}</option><option
						value="false">{$t('Without PDF')}</option
					></select
				></label
			>
		{:else if section === 'audit'}
			<label>{$t('Action')}<input class="compact input" bind:value={filterA} /></label>
			<label>{$t('Target type')}<input class="compact input" bind:value={filterB} /></label>
		{:else}
			<label
				>{$t('State')}<select class="compact input" bind:value={filterA}
					><option value="">{$t('Any state')}</option><option value="pending"
						>{$t('Pending')}</option
					><option value="running">{$t('Running')}</option><option value="succeeded"
						>{$t('Succeeded')}</option
					><option value="failed">{$t('Failed')}</option><option value="cancelled"
						>{$t('Cancelled')}</option
					></select
				></label
			>
		{/if}
		<button class="btn preset-filled-primary-700-300 font-semibold">{$t('Apply filters')}</button>
		<button type="button" class="btn preset-tonal-surface font-semibold" onclick={clearFilters}
			>{$t('Clear filters')}</button
		>
	</form>
{/if}
{#if error}<p class="text-error-700" role="alert">{error}</p>{/if}{#if notice}<p
		class="rounded-base border border-success-200 preset-tonal-success px-4 py-3 text-success-900"
		role="status"
	>
		{$t(notice)}
	</p>{/if}
{#if data.isPending}<p class="text-surface-600">
		{$t('Loading')}
		{$t(sectionLabel).toLowerCase()}…
	</p>
{:else if data.isError}<p class="text-error-700">{$t('Unable to load administration.')}</p>
{:else if data.data}
	{#if section === 'overview'}
		{@const overview = data.data as Overview}
		<div class="stat-grid admin-stats">
			<div><strong>{overview.user_count}</strong><span>{$t('Users')}</span></div>
			<div>
				<strong>{overview.pending_invitation_count}</strong><span>{$t('Pending invitations')}</span>
			</div>
			<div><strong>{overview.storage.items_count}</strong><span>{$t('Items')}</span></div>
			<div>
				<strong>{overview.failed_workflows.length}</strong><span>{$t('Failed workflows')}</span>
			</div>
		</div>
		<section class="list-panel card border border-surface-300 bg-surface-50 p-5 shadow-sm">
			<h2>{$t('Recent audit events')}</h2>
			{#each overview.recent_events as event (event.id)}<div class="item-row">
					<strong>{event.action}</strong><span class="text-surface-600"
						>{event.target_type} · {new Date(event.created_at).toLocaleString()}</span
					>
				</div>{:else}<p class="text-surface-600">{$t('No audit events.')}</p>{/each}
		</section>
	{:else if section === 'users'}
		{@const users = data.data as Users}
		<div class="item-layout">
			<section class="list-panel card border border-surface-300 bg-surface-50 p-5 shadow-sm">
				<h2>{$t('Users')} ({users.total})</h2>
				{#each users.users as user (user.id)}
					<div class="item-row admin-user-row">
						<div>
							<strong>{user.username}</strong><span class="text-surface-600"
								>{$t(domainLabel(user.role))} · {user.active ? $t('active') : $t('disabled')}</span
							>
						</div>
						<div class="admin-user-actions">
							<form class="toolbar" onsubmit={(event) => updateUserRole(event, user.id)}>
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
								onclick={() => updateUserStatus(user)}
								>{user.active ? $t('Disable user') : $t('Enable user')}</button
							>
							<form class="toolbar" onsubmit={(event) => resetUserPassword(event, user.id)}>
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
								onclick={() => revokeUserSessions(user.id)}>{$t('Revoke sessions')}</button
							>
						</div>
					</div>
				{:else}
					<p class="text-surface-600">{$t('No users.')}</p>
				{/each}
				<h2>{$t('Invitations')}</h2>
				{#each users.invitations as invitation (invitation.id)}<div class="item-row">
						<strong>{invitation.username}</strong><span class="text-surface-600"
							>{$t(domainLabel(invitation.role))} · {invitation.accepted_at
								? $t('accepted')
								: $t('pending')}</span
						>
					</div>{:else}<p class="text-surface-600">{$t('No invitations.')}</p>{/each}
			</section>
			<aside class="stack">
				<form
					class="stack card border border-surface-300 bg-surface-50 p-5 shadow-sm"
					onsubmit={createUser}
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
					class="stack card border border-surface-300 bg-surface-50 p-5 shadow-sm"
					onsubmit={createInvitation}
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
					{#if invitationUrl}<div class="secret" role="status">
							<strong>{$t('Copy this invitation URL now')}</strong><a
								href={invitationUrl}
								rel="external">{invitationUrl}</a
							>
						</div>{/if}
				</form>
			</aside>
		</div>
	{:else if section === 'projects'}
		{@const projects = (data.data as { projects: Project[]; total: number }).projects}
		<section class="list-panel card border border-surface-300 bg-surface-50 p-5 shadow-sm">
			<h2>{$t('Projects')}</h2>
			{#each projects as project (project.id)}<div class="item-row">
					<strong>{project.name}</strong><span>{project.description}</span><span
						class="text-surface-600"
						>{$t(domainLabel(project.visibility))} · {$t(domainLabel(project.state))} · {project.member_count}
						{$t('members')} · {project.item_count}
						{$t('Items')} · {project.creator.username}</span
					>
				</div>{:else}<p class="text-surface-600">{$t('No projects.')}</p>{/each}
		</section>
	{:else if section === 'items'}
		{@const items = data.data as {
			items: ItemSummary[];
			total: number;
			storage: { total_disk_bytes: number };
		}}
		<section class="list-panel card border border-surface-300 bg-surface-50 p-5 shadow-sm">
			<h2>{$t('Items')} ({items.total})</h2>
			<p class="text-surface-600">
				{Math.ceil(items.storage.total_disk_bytes / 1048576)} MB stored
			</p>
			{#each items.items as item (item.id)}<div
					class="item-row grid-cols-[minmax(0,1fr)_auto] items-center"
				>
					<a
						class="grid gap-1 no-underline"
						href={resolve('/(app)/item/[itemId]', { itemId: item.id })}
						><strong><RichText html={item.title_html} /></strong><span class="text-surface-600"
							>{item.authors ?? $t('Unknown authors')}</span
						></a
					><button
						class="btn preset-tonal-error font-semibold"
						disabled={busy}
						onclick={() => deleteAdminItem(item.id)}>{$t('Delete')}</button
					>
				</div>{:else}<p class="text-surface-600">{$t('No Items.')}</p>{/each}
		</section>
	{:else if section === 'audit'}
		{@const events = (data.data as { events: AuditEvent[] }).events}
		<section class="list-panel card border border-surface-300 bg-surface-50 p-5 shadow-sm">
			<h2>{$t('Audit log')}</h2>
			{#each events as event (event.id)}<div class="item-row">
					<strong>{event.action}</strong><span
						>{event.target_type}{event.target_id ? ` · ${event.target_id}` : ''}</span
					><span class="text-surface-600"
						>{event.actor_id ? `${$t('Actor')} ${event.actor_id} · ` : ''}{new Date(
							event.created_at
						).toLocaleString()}</span
					>
					{#if event.detail}<pre
							class="overflow-x-auto rounded bg-surface-200 p-2 text-xs">{typeof event.detail ===
							'string'
								? event.detail
								: JSON.stringify(event.detail, null, 2)}</pre>{/if}
				</div>{:else}<p class="text-surface-600">{$t('No audit events.')}</p>{/each}
		</section>
	{:else if section === 'workflows'}
		{@const workflows = (data.data as { workflows: Workflow[] }).workflows}
		<section class="list-panel card border border-surface-300 bg-surface-50 p-5 shadow-sm">
			<h2>{$t('Durable workflows')}</h2>
			{#each workflows as workflow (workflow.id)}<div class="item-row">
					<strong>{workflow.name || workflow.id || $t('Workflow')}</strong><span
						class="text-surface-600"
						>{$t(domainLabel(workflow.state))}{workflow.error ? ` · ${workflow.error}` : ''}</span
					>
				</div>{:else}<p class="text-surface-600">{$t('No workflows.')}</p>{/each}
		</section>
	{:else if section === 'settings'}
		{@const settings = data.data as Settings}
		<section class="stack card border border-surface-300 bg-surface-50 p-5 shadow-sm">
			<h2>{$t('Runtime settings')}</h2>
			<form class="stack" onsubmit={saveSettings}>
				{#each settingFields as [key, label] (key)}<label
						>{$t(label)}<input
							class="input"
							name={key}
							type={typeof settings[key] === 'number' ? 'number' : 'text'}
							value={settings[key]}
							required={typeof settings[key] === 'number'}
						/></label
					>{/each}
				<p class="text-surface-600">
					Database: {settings.database_url}<br />Data directory: {settings.data_dir}
				</p>
				<button class="btn preset-filled-primary-700-300 font-semibold" disabled={busy}
					>{$t('Save settings')}</button
				>
			</form>
		</section>
	{:else}
		{@const maintenance = data.data as {
			storage: { items_count: number; total_disk_bytes: number };
			workflows: Workflow[];
		}}
		<section class="stack card border border-surface-300 bg-surface-50 p-5 shadow-sm">
			<h2>{$t('Maintenance')}</h2>
			<p>
				{maintenance.storage.items_count} Items · {Math.ceil(
					maintenance.storage.total_disk_bytes / 1048576
				)} MB
			</p>
			<div class="toolbar">
				{#each maintenanceOperations as [operation, label] (operation)}<button
						class="btn preset-tonal-surface font-semibold"
						disabled={busy}
						onclick={() => runMaintenance(operation)}>{$t(label)}</button
					>{/each}
			</div>
			<h3>{$t('Recent operations')}</h3>
			{#each maintenance.workflows as workflow (workflow.id)}<div class="item-row">
					<strong>{workflow.name || workflow.id || $t('Operation')}</strong><span
						class="text-surface-600">{$t(domainLabel(workflow.state))}</span
					>
					{#if workflow.state === 'succeeded' && (workflow.name ?? '').includes('backup') && workflow.id}<button
							class="btn preset-tonal-surface font-semibold"
							onclick={() => downloadBackup(workflow.id)}>{$t('Download backup')}</button
						>{/if}
				</div>{:else}<p class="text-surface-600">{$t('No maintenance workflows.')}</p>{/each}
		</section>
	{/if}
	{#if pagination?.total !== undefined && pageCount > 1}
		<nav class="pagination" aria-label={$t('Administration pages')}>
			<button
				class="btn preset-tonal-surface font-semibold"
				disabled={adminPage <= 1}
				onclick={() => (adminPage -= 1)}>{$t('Previous')}</button
			><span>{$t('Page')} {adminPage} / {pageCount}</span><button
				class="btn preset-tonal-surface font-semibold"
				disabled={adminPage >= pageCount}
				onclick={() => (adminPage += 1)}>{$t('Next')}</button
			>
		</nav>
	{/if}
{/if}
