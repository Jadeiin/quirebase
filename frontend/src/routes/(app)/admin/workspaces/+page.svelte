<script lang="ts">
	import SearchSelect from '#lib/design/SearchSelect.svelte';
	import { createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { apiRequest } from '#lib/api/client.js';
	import { apiErrorMessage } from '#lib/api/errors.js';
	import Button from '#lib/design/Button.svelte';
	import Badge from '#lib/design/Badge.svelte';
	import WorkspaceOwnerReassign from '#lib/features/admin/WorkspaceOwnerReassign.svelte';
	import Notice from '#lib/design/Notice.svelte';
	import RichText from '#lib/design/RichText.svelte';
	import { adminWorkspacesQuery } from '#lib/features/admin/queries.js';
	import { getAdminFilters } from '#lib/features/admin/filters.js';
	import { invalidateWorkspaces } from '#lib/query/invalidation.js';
	import { t } from '#lib/i18n.js';
	import { domainLabel } from '#lib/domain-labels.js';
	import type { components } from '#lib/api/schema.js';

	type ReassignmentForm = { workspaceId: string };

	const { filters } = getAdminFilters();
	const queryClient = useQueryClient();
	const workspaces = createQuery(() => adminWorkspacesQuery());
	const search = $derived(filters().search.toLowerCase());
	const visibleWorkspaces = $derived(
		(workspaces.data ?? []).filter(
			(workspace) => workspace.id === reassignment?.workspaceId || matchesSearch(workspace)
		)
	);
	let error = $state('');
	let busyId = $state('');
	let reassignment = $state<ReassignmentForm | null>(null);
	let targetId = $state('');
	let reason = $state('');
	let inspection = $state<components['schemas']['ItemSearchView'][] | undefined>();
	let inspectionReason = $state('');
	let inspectionWorkspaceId = $state('');

	function matchesSearch(workspace: components['schemas']['AdminWorkspaceView']) {
		return [workspace.name, workspace.id, workspace.owner_username, workspace.owner_id].some(
			(value) => value.toLowerCase().includes(search)
		);
	}

	function toggleReassignment(workspaceId: string) {
		reassignment = reassignment?.workspaceId === workspaceId ? null : { workspaceId };
	}

	function closeReassignment(form: ReassignmentForm) {
		return () => {
			// A completed request may belong to an already replaced form, even for the same Workspace.
			if (reassignment === form) reassignment = null;
		};
	}

	async function govern(workspaceId: string, operation: 'freeze' | 'unfreeze') {
		busyId = workspaceId;
		error = '';
		try {
			if (operation === 'freeze')
				await apiRequest('POST', '/admin/workspaces/{workspace_id}/freeze', {
					params: { path: { workspace_id: workspaceId } }
				});
			else
				await apiRequest('POST', '/admin/workspaces/{workspace_id}/unfreeze', {
					params: { path: { workspace_id: workspaceId } }
				});
			await Promise.all([
				workspaces.refetch(),
				queryClient.invalidateQueries({ queryKey: ['admin'] }),
				invalidateWorkspaces(queryClient)
			]);
		} catch (failure) {
			error = apiErrorMessage(failure, 'Workspace governance action failed');
		} finally {
			busyId = '';
		}
	}

	async function inspect() {
		const requestedWorkspaceId = targetId;
		const requestedReason = reason.trim();
		if (!requestedWorkspaceId || requestedReason.length < 10) return;
		busyId = 'break-glass';
		error = '';
		inspection = undefined;
		try {
			inspection = await apiRequest('POST', '/admin/workspaces/{workspace_id}/break-glass/items', {
				params: { path: { workspace_id: requestedWorkspaceId } },
				body: { reason: requestedReason }
			});
			inspectionReason = requestedReason;
			inspectionWorkspaceId = requestedWorkspaceId;
		} catch (failure) {
			error = apiErrorMessage(failure, 'Break-glass inspection was denied');
		} finally {
			busyId = '';
		}
	}
</script>

<section class="grid grid-cols-1 gap-6">
	<header>
		<h2 class="text-2xl font-bold">{$t('Workspace governance')}</h2>
		<p class="text-sm text-surface-600-400">
			{$t(
				'Manage Workspace owners and freezes. Reassigning ownership grants access to the selected user; freezing writes preserves active members’ read and export access.'
			)}
		</p>
	</header>
	{#if error}<Notice variant="error">{error}</Notice>{/if}
	{#if workspaces.isError}
		<Notice as="div" variant="error" class="flex flex-wrap items-center justify-between gap-3">
			<span>{$t('Unable to load workspaces.')}</span>
			<Button disabled={workspaces.isFetching} onclick={() => void workspaces.refetch()}
				>{$t('Retry')}</Button
			>
		</Notice>
	{/if}
	{#if workspaces.isPending}<p>
			{$t('Loading workspaces…')}
		</p>{:else if visibleWorkspaces.length}<div class="grid grid-cols-1 gap-3">
			{#each visibleWorkspaces as workspace (workspace.id)}<article
					class="flex flex-wrap items-center justify-between gap-3 rounded-container border border-surface-300-700 p-4"
				>
					<div class="min-w-0">
						<strong>{workspace.name}</strong>
						<p class="text-xs break-all text-surface-600-400">
							{workspace.id} · {$t(domainLabel(workspace.state))} · {$t('owner')}
							{workspace.owner_username}{workspace.governance_frozen_at
								? ` · ${$t('read-only freeze')} ${new Date(workspace.governance_frozen_at).toLocaleString()}`
								: ''}
						</p>
						{#if !workspace.owner_active}<Badge variant="warning"
								>{$t('Owner account disabled')}</Badge
							>{/if}
					</div>
					<div class="flex flex-wrap gap-2">
						{#if workspace.can_reassign_owner}<Button
								size="sm"
								disabled={busyId !== ''}
								onclick={() => toggleReassignment(workspace.id)}
								aria-expanded={reassignment?.workspaceId === workspace.id}
								>{$t('Reassign owner')}</Button
							>{/if}
						{#if workspace.governance_frozen_at}<Button
								size="sm"
								disabled={busyId !== ''}
								onclick={() => void govern(workspace.id, 'unfreeze')}
								>{$t('Unfreeze writes')}</Button
							>{:else}<Button
								size="sm"
								variant="tonal"
								disabled={busyId !== ''}
								onclick={() => void govern(workspace.id, 'freeze')}>{$t('Freeze writes')}</Button
							>{/if}
					</div>
					{#if reassignment && reassignment.workspaceId === workspace.id}
						{#if !matchesSearch(workspace)}
							<Notice class="w-full">
								{$t('This Workspace stays visible while its owner reassignment form is open.')}
							</Notice>
						{/if}
						<WorkspaceOwnerReassign
							{workspace}
							onClose={closeReassignment(reassignment)}
							onError={(message) => {
								error = message ? `${workspace.name}: ${message}` : '';
							}}
						/>
					{/if}
				</article>{/each}
		</div>{:else if workspaces.data}<p>
			{filters().search ? $t('No matching workspaces.') : $t('No workspaces.')}
		</p>{/if}
	<section
		class="grid max-w-3xl grid-cols-1 gap-3 rounded-container border border-warning-500 p-5 dark:border-warning-300"
	>
		<h3 class="text-xl font-semibold">{$t('BREAK GLASS · read-only item inspection')}</h3>
		<p>
			{$t(
				'Each inspection requires a reason and returns at most 100 Items. It grants no continuing access.'
			)}
		</p>
		<SearchSelect
			label={$t('Target Workspace')}
			emptyLabel={$t('Choose a Workspace')}
			bind:value={targetId}
			disabled={busyId !== ''}
			options={(workspaces.data ?? []).map((workspace) => ({
				value: workspace.id,
				label: workspace.name
			}))}
		/>
		<label class="grid grid-cols-1 gap-1"
			>{$t('Reason (at least 10 characters)')}<textarea
				class="input"
				bind:value={reason}
				minlength="10"
				maxlength="1000"></textarea></label
		>
		<Button
			disabled={busyId !== '' || reason.trim().length < 10 || !targetId}
			onclick={() => void inspect()}>{$t('Inspect Items once')}</Button
		>
		{#if inspection}<aside class="grid grid-cols-1 gap-2 rounded-md bg-warning-100-900 p-4">
				<strong>{$t('BREAK GLASS')}</strong><span>{$t('Reason:')} {inspectionReason}</span><span
					>{$t('Scope: Workspace')} {inspectionWorkspaceId} · {$t('Item list read-only')}</span
				><span>{$t('Single response; no continuing access is granted')}</span
				>{#each inspection as item (item.id)}<div
						class="border-t border-surface-400 pt-2 dark:border-surface-700"
					>
						<RichText html={item.title_html} /><small class="block text-surface-600-400"
							>{item.authors.map((author) => author.full_name).join('; ')} · {item.publication_date ??
								''}</small
						>
					</div>{:else}<p>{$t('No Items found.')}</p>{/each}
			</aside>{/if}
	</section>
</section>
