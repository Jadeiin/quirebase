<script lang="ts">
	import { resolve } from '$app/paths';
	import { createMutation, createQuery } from '@tanstack/svelte-query';
	import { apiRequest } from '$lib/api/client';
	import { apiErrorMessage } from '$lib/api/errors';
	import ConfirmDialog from '$lib/design/ConfirmDialog.svelte';
	import Notice from '$lib/design/Notice.svelte';
	import Panel from '$lib/design/Panel.svelte';
	import Pagination from '$lib/design/Pagination.svelte';
	import SectionTab from '$lib/design/SectionTab.svelte';
	import SectionTabs from '$lib/design/SectionTabs.svelte';
	import SectionHeader from '$lib/design/SectionHeader.svelte';
	import { getWorkflowCenter } from '$lib/features/workflows/center.svelte';
	import AdminAudit from '$lib/features/admin/AdminAudit.svelte';
	import AdminItems from '$lib/features/admin/AdminItems.svelte';
	import AdminMaintenance from '$lib/features/admin/AdminMaintenance.svelte';
	import AdminOverview from '$lib/features/admin/AdminOverview.svelte';
	import AdminProjects from '$lib/features/admin/AdminProjects.svelte';
	import AdminSettings from '$lib/features/admin/AdminSettings.svelte';
	import AdminUsers from '$lib/features/admin/AdminUsers.svelte';
	import AdminWorkflows from '$lib/features/admin/AdminWorkflows.svelte';
	import { adminMutationOptions } from '$lib/features/admin/mutations';
	import {
		adminAuditQuery,
		adminItemsQuery,
		adminMaintenanceQuery,
		adminOverviewQuery,
		adminProjectsQuery,
		adminSettingsQuery,
		adminUsersQuery,
		adminWorkflowsQuery,
		type AdminFilters,
		type AdminSection
	} from '$lib/features/admin/queries';
	import { msg, t, type MessageKey } from '$lib/i18n';
	import type { components } from '$lib/api/schema';
	import Button from '$lib/design/Button.svelte';

	type User = components['schemas']['AdminUserView'];
	type Settings = components['schemas']['AdminSettingsView'];
	type InvitationCreated = components['schemas']['AdminInvitationCreatedView'];

	let { section } = $props<{ section: AdminSection }>();
	let error = $state('');
	let notice = $state<MessageKey | null>(null);
	let invitationUrl = $state('');
	let adminPage = $state(1);
	let searchInput = $state('');
	let appliedSearch = $state('');
	let filterA = $state('');
	let appliedFilterA = $state('');
	let filterB = $state('');
	let appliedFilterB = $state('');
	let pendingItemId = $state<string | null>(null);
	let confirmDeleteOpen = $state(false);
	const workflowCenter = getWorkflowCenter();
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
	function filters(): AdminFilters {
		return {
			page: adminPage,
			search: appliedSearch,
			filterA: appliedFilterA,
			filterB: appliedFilterB
		};
	}
	const overview = createQuery(() => adminOverviewQuery(filters(), section === 'overview'));
	const users = createQuery(() => adminUsersQuery(filters(), section === 'users'));
	const projects = createQuery(() => adminProjectsQuery(filters(), section === 'projects'));
	const items = createQuery(() => adminItemsQuery(filters(), section === 'items'));
	const audit = createQuery(() => adminAuditQuery(filters(), section === 'audit'));
	const workflows = createQuery(() => adminWorkflowsQuery(filters(), section === 'workflows'));
	const settings = createQuery(() => adminSettingsQuery(filters(), section === 'settings'));
	const maintenance = createQuery(() =>
		adminMaintenanceQuery(filters(), section === 'maintenance')
	);
	function refetchSection(): Promise<unknown> {
		switch (section) {
			case 'overview':
				return overview.refetch();
			case 'users':
				return users.refetch();
			case 'projects':
				return projects.refetch();
			case 'items':
				return items.refetch();
			case 'audit':
				return audit.refetch();
			case 'workflows':
				return workflows.refetch();
			case 'settings':
				return settings.refetch();
			case 'maintenance':
				return maintenance.refetch();
			default:
				return Promise.resolve();
		}
	}
	const adminMutation = createMutation(() => adminMutationOptions(section, refetchSection));
	const busy = $derived(adminMutation.isPending);
	const sectionPending = $derived.by(() => {
		switch (section) {
			case 'overview':
				return overview.isPending;
			case 'users':
				return users.isPending;
			case 'projects':
				return projects.isPending;
			case 'items':
				return items.isPending;
			case 'audit':
				return audit.isPending;
			case 'workflows':
				return workflows.isPending;
			case 'settings':
				return settings.isPending;
			case 'maintenance':
				return maintenance.isPending;
		}
	});
	const sectionError = $derived.by(() => {
		switch (section) {
			case 'overview':
				return overview.isError;
			case 'users':
				return users.isError;
			case 'projects':
				return projects.isError;
			case 'items':
				return items.isError;
			case 'audit':
				return audit.isError;
			case 'workflows':
				return workflows.isError;
			case 'settings':
				return settings.isError;
			case 'maintenance':
				return maintenance.isError;
		}
	});
	const pagination = $derived.by(() => {
		switch (section) {
			case 'users':
				return users.data;
			case 'projects':
				return projects.data;
			case 'items':
				return items.data;
			case 'audit':
				return audit.data;
			default:
				return undefined;
		}
	});
	const pageCount = $derived(
		pagination?.total && pagination.per_page
			? Math.max(1, Math.ceil(pagination.total / pagination.per_page))
			: 1
	);

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

	function mutate(
		operation: () => Promise<unknown>,
		success: MessageKey,
		form?: HTMLFormElement,
		onSuccess?: (result: unknown) => void,
		failureMessage = $t('Administration action failed'),
		pendingNotice: MessageKey | null = null
	) {
		error = '';
		notice = pendingNotice;
		void adminMutation
			.mutateAsync({ run: operation, form })
			.then((result) => {
				onSuccess?.(result);
				notice = success;
			})
			.catch((reason) => {
				error = apiErrorMessage(reason, failureMessage);
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

	function saveSettings(event: SubmitEvent) {
		event.preventDefault();
		const form = event.currentTarget as HTMLFormElement;
		const values: Record<string, FormDataEntryValue | number> = Object.fromEntries(
			new FormData(form)
		);
		for (const key of ['session_days', 'max_pdf_bytes', 'max_attachment_bytes', 'export_ttl_hours'])
			values[key] = Number(values[key]);
		void mutate(
			() => apiRequest('PUT', '/admin/settings', { body: values as Settings }),
			msg('Settings saved')
		);
	}

	function runMaintenance(operation: (typeof maintenanceOperations)[number][0]) {
		void mutate(
			async () => {
				const started = await apiRequest('POST', '/admin/maintenance/{operation}', {
					params: { path: { operation } }
				});
				await workflowCenter.track(started.id, {
					label: `${$t('Maintenance')}: ${$t(maintenanceOperations.find(([key]) => key === operation)?.[1] ?? operation)}`,
					successMessage: msg('Maintenance operation completed'),
					failureMessage: msg('Maintenance operation failed')
				}).settled;
			},
			msg('Maintenance operation completed'),
			undefined,
			undefined,
			$t('Maintenance operation failed'),
			msg('Maintenance operation started')
		);
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

	function downloadBackup(workflowId: string) {
		location.assign(`/api/v1/admin/maintenance/backups/${workflowId}/content`);
	}
</script>

<SectionHeader>
	<div>
		<h1>{$t('Administration')}</h1>
		<p class="text-surface-700-300">
			{$t('Users, storage, audit, settings, and durable operations.')}
		</p>
	</div>
</SectionHeader>
<SectionTabs label={$t('Administration sections')}>
	{#each Object.entries(labels) as [key, label] (key)}
		<SectionTab href={resolve(sectionPath(key))} current={section === key}>{$t(label)}</SectionTab>
	{/each}
</SectionTabs>
{#if ['users', 'projects', 'items', 'audit', 'workflows'].includes(section)}
	<Panel as="form" class="mb-4 flex flex-wrap items-end gap-2" onsubmit={applyFilters}>
		{#if section !== 'workflows'}
			<label class="grow basis-64"
				>{$t('Search')}<input class="input" bind:value={searchInput} /></label
			>
		{/if}
		{#if section === 'users'}
			<label
				>{$t('Role')}<select class="input w-auto min-w-36" bind:value={filterA}
					><option value="">{$t('All roles')}</option><option value="member">{$t('Member')}</option
					><option value="administrator">{$t('Administrator')}</option></select
				></label
			>
			<label
				>{$t('Status')}<select class="input w-auto min-w-36" bind:value={filterB}
					><option value="">{$t('Any status')}</option><option value="true">{$t('Active')}</option
					><option value="false">{$t('Disabled')}</option></select
				></label
			>
		{:else if section === 'projects'}
			<label
				>{$t('State')}<select class="input w-auto min-w-36" bind:value={filterA}
					><option value="">{$t('Any state')}</option><option value="active">{$t('Active')}</option
					><option value="archived">{$t('Archived')}</option></select
				></label
			>
			<label
				>{$t('Visibility')}<select class="input w-auto min-w-36" bind:value={filterB}
					><option value="">{$t('Any visibility')}</option><option value="private"
						>{$t('Private')}</option
					><option value="public">{$t('Public')}</option></select
				></label
			>
		{:else if section === 'items'}
			<label
				>{$t('PDF availability')}<select class="input w-auto min-w-36" bind:value={filterA}
					><option value="">{$t('Any')}</option><option value="true">{$t('Has PDF')}</option><option
						value="false">{$t('Without PDF')}</option
					></select
				></label
			>
		{:else if section === 'audit'}
			<label>{$t('Action')}<input class="input w-auto min-w-36" bind:value={filterA} /></label>
			<label>{$t('Target type')}<input class="input w-auto min-w-36" bind:value={filterB} /></label>
		{:else}
			<label
				>{$t('State')}<select class="input w-auto min-w-36" bind:value={filterA}
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
		<Button variant="filled">{$t('Apply filters')}</Button>
		<Button type="button" onclick={clearFilters}>{$t('Clear filters')}</Button>
	</Panel>
{/if}
{#if error}<Notice variant="error">{error}</Notice>{/if}{#if notice}<Notice variant="success"
		>{$t(notice)}</Notice
	>{/if}
{#if sectionPending}<p class="text-surface-600-400">
		{$t('Loading')}
		{$t(sectionLabel).toLowerCase()}…
	</p>
{:else if sectionError}<p class="text-error-700-300">{$t('Unable to load administration.')}</p>
{:else}
	{#if section === 'overview'}
		<AdminOverview overview={overview.data!} />
	{:else if section === 'users'}
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
	{:else if section === 'projects'}
		<AdminProjects projects={projects.data!.projects} />
	{:else if section === 'items'}
		<AdminItems items={items.data!} {busy} onDelete={deleteAdminItem} />
		<ConfirmDialog
			bind:open={confirmDeleteOpen}
			title={$t('Permanently delete this Item?')}
			body={$t('This cannot be undone.')}
			confirmLabel={$t('Permanently delete')}
			{busy}
			onConfirm={confirmDeleteAdminItem}
		/>
	{:else if section === 'audit'}
		<AdminAudit events={audit.data!.events} />
	{:else if section === 'workflows'}
		<AdminWorkflows workflows={workflows.data!.workflows} />
	{:else if section === 'settings'}
		<AdminSettings settings={settings.data!} fields={settingFields} {busy} onSave={saveSettings} />
	{:else}
		<AdminMaintenance
			maintenance={maintenance.data!}
			operations={maintenanceOperations}
			{busy}
			onRun={runMaintenance}
			onDownloadBackup={downloadBackup}
		/>
	{/if}
	{#if pagination?.total !== undefined && pageCount > 1}
		<Pagination
			page={adminPage}
			{pageCount}
			label={$t('Administration pages')}
			onPage={(next) => (adminPage = next)}
		/>
	{/if}
{/if}
