<script lang="ts">
	import { createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { apiRequest } from '#lib/api/client.js';
	import { apiErrorMessage } from '#lib/api/errors.js';
	import type { components } from '#lib/api/schema.js';
	import Button from '#lib/design/Button.svelte';
	import Notice from '#lib/design/Notice.svelte';
	import Pagination from '#lib/design/Pagination.svelte';
	import QueryError from '#lib/design/QueryError.svelte';
	import RichText from '#lib/design/RichText.svelte';
	import SearchSelect from '#lib/design/SearchSelect.svelte';
	import AdminSectionState from '#lib/features/admin/AdminSectionState.svelte';
	import AdminWorkspaces from '#lib/features/admin/AdminWorkspaces.svelte';
	import WorkspaceOwnerReassign from '#lib/features/admin/WorkspaceOwnerReassign.svelte';
	import { getAdminFilters } from '#lib/features/admin/filters.js';
	import { adminWorkspaceOptionsQuery, adminWorkspacesQuery } from '#lib/features/admin/queries.js';
	import { isAdminUnavailableError } from '#lib/features/admin/read-state.js';
	import { msg, t } from '#lib/i18n.js';
	import { invalidateWorkspaces } from '#lib/query/invalidation.js';

	type Workspace = components['schemas']['AdminWorkspaceView'];
	type ReassignmentForm = { workspace: Workspace };
	const { filters, setPage, correctPage, setPageSize } = getAdminFilters();
	const queryClient = useQueryClient();
	const workspaces = createQuery(() => adminWorkspacesQuery(filters(), true));
	let reassignment = $state<ReassignmentForm | null>(null);
	let error = $state('');
	let notice = $state('');
	let busyId = $state('');
	let breakGlassOpen = $state(false);
	let targetSearch = $state<string | null>(null);
	let targetId = $state('');
	let selectedTarget = $state<Workspace>();
	let reason = $state('');
	let inspection = $state<components['schemas']['ItemSearchView'][] | undefined>();
	let inspectionReason = $state('');
	let inspectionWorkspaceId = $state('');
	const workspaceOptions = createQuery(() =>
		adminWorkspaceOptionsQuery(targetSearch ?? '', breakGlassOpen)
	);
	const inspectionUnavailable = $derived(
		workspaces.data === null ||
			workspaceOptions.data === null ||
			isAdminUnavailableError(workspaces.error) ||
			isAdminUnavailableError(workspaceOptions.error)
	);
	const pageCount = $derived(
		Math.max(1, Math.ceil((workspaces.data?.total ?? 0) / filters().pageSize))
	);

	$effect(() => {
		if (workspaces.isSuccess && !workspaces.isFetching && workspaces.data) correctPage(pageCount);
	});
	$effect(() => {
		if (inspectionUnavailable) {
			inspection = undefined;
			inspectionReason = '';
			inspectionWorkspaceId = '';
		}
	});

	function toggleReassignment(workspace: Workspace) {
		reassignment = reassignment?.workspace.id === workspace.id ? null : { workspace };
	}
	function closeReassignment(form: ReassignmentForm) {
		return () => {
			// Even a new form for the same Workspace has its own completion boundary.
			if (reassignment === form) reassignment = null;
		};
	}
	function reassignmentError(form: ReassignmentForm) {
		return (message: string) => {
			error = message ? `${form.workspace.name}: ${message}` : '';
		};
	}
	async function refreshGovernance() {
		await Promise.all([
			queryClient.invalidateQueries({ queryKey: ['admin'] }),
			invalidateWorkspaces(queryClient)
		]);
	}
	async function govern(workspace: Workspace, operation: 'freeze' | 'unfreeze') {
		if (busyId || workspaces.data === null || isAdminUnavailableError(workspaces.error)) return;
		busyId = workspace.id;
		error = '';
		notice = '';
		try {
			if (operation === 'freeze')
				await apiRequest('POST', '/admin/workspaces/{workspace_id}/freeze', {
					params: { path: { workspace_id: workspace.id } }
				});
			else
				await apiRequest('POST', '/admin/workspaces/{workspace_id}/unfreeze', {
					params: { path: { workspace_id: workspace.id } }
				});
			notice =
				operation === 'freeze' ? $t('Workspace writes frozen') : $t('Workspace writes unfrozen');
			await refreshGovernance();
		} catch (failure) {
			error = apiErrorMessage(failure, $t('Workspace governance action failed'));
		} finally {
			busyId = '';
		}
	}
	function selectTarget(workspaceId: string) {
		selectedTarget =
			workspaceOptions.data?.items.find((workspace) => workspace.id === workspaceId) ??
			(selectedTarget?.id === workspaceId ? selectedTarget : undefined);
		targetId = workspaceId;
	}
	async function inspect() {
		const requestedWorkspaceId = targetId;
		const requestedReason = reason.trim();
		if (busyId || inspectionUnavailable || !requestedWorkspaceId || requestedReason.length < 10)
			return;
		busyId = 'break-glass';
		error = '';
		notice = '';
		inspection = undefined;
		try {
			const items = await apiRequest('POST', '/admin/workspaces/{workspace_id}/break-glass/items', {
				params: { path: { workspace_id: requestedWorkspaceId } },
				body: { reason: requestedReason }
			});
			if (!inspectionUnavailable) {
				inspection = items;
				inspectionReason = requestedReason;
				inspectionWorkspaceId = requestedWorkspaceId;
			}
		} catch (failure) {
			error = apiErrorMessage(failure, $t('Break-glass inspection was denied'));
		} finally {
			busyId = '';
		}
	}
</script>

<section class="grid min-w-0 grid-cols-1 gap-6">
	<header>
		<h2 class="text-2xl font-bold">{$t('Workspace governance')}</h2>
		<p class="text-sm text-surface-600-400">
			{$t(
				'Manage Workspace owners and freezes. Reassigning ownership grants access to the selected user; freezing writes preserves active members’ read and export access.'
			)}
		</p>
	</header>
	{#if error}<Notice variant="error">{error}</Notice>{/if}
	{#if notice}<Notice variant="success">{notice}</Notice>{/if}
	{#if reassignment}
		{#key reassignment}
			<WorkspaceOwnerReassign
				workspace={reassignment.workspace}
				onClose={closeReassignment(reassignment)}
				onError={reassignmentError(reassignment)}
			/>
		{/key}
	{/if}
	<AdminSectionState
		available={workspaces.data != null}
		error={workspaces.error}
		busy={workspaces.isFetching}
		onRetry={() => void workspaces.refetch()}
		loading={workspaces.isPending}
		failed={workspaces.isError}
		label={msg('Workspaces')}
	>
		<AdminWorkspaces
			workspaces={workspaces.data!.items}
			total={workspaces.data!.total}
			busy={busyId !== ''}
			refreshing={workspaces.isFetching}
			reassignmentId={reassignment?.workspace.id}
			onRefresh={() => void workspaces.refetch()}
			onReassign={toggleReassignment}
			onGovern={(workspace, operation) => void govern(workspace, operation)}
		/>
		<Pagination
			page={filters().page}
			{pageCount}
			pageSize={filters().pageSize}
			total={workspaces.data?.total ?? 0}
			busy={workspaces.isFetching}
			onPageSize={setPageSize}
			label={$t('Administration pages')}
			onPage={setPage}
		/>
	</AdminSectionState>
	<details
		bind:open={breakGlassOpen}
		class="min-w-0 rounded-container border border-warning-500 p-5 dark:border-warning-300"
	>
		<summary class="cursor-pointer text-lg font-semibold"
			>{$t('BREAK GLASS · read-only item inspection')}</summary
		>
		<div class="mt-4 grid max-w-3xl min-w-0 grid-cols-1 gap-3">
			<p>
				{$t(
					'Each inspection requires a reason and returns at most 100 Items. It grants no continuing access.'
				)}
			</p>
			{#if workspaceOptions.isError || workspaceOptions.data === null}
				<QueryError
					message={$t('Unable to load workspaces.')}
					busy={workspaceOptions.isFetching}
					onRetry={() => void workspaceOptions.refetch()}
				/>
			{/if}
			<SearchSelect
				label={$t('Target Workspace')}
				emptyLabel={$t('Choose a Workspace')}
				placeholder={$t('Search')}
				bind:value={() => targetId, selectTarget}
				bind:search={targetSearch}
				selectedLabel={selectedTarget?.id === targetId ? selectedTarget.name : undefined}
				disabled={busyId !== '' || inspectionUnavailable}
				filterOptions={false}
				loading={workspaceOptions.isFetching}
				options={(workspaceOptions.data?.items ?? []).map((workspace) => ({
					value: workspace.id,
					label: workspace.name
				}))}
			/>
			<p class="text-xs text-surface-600-400">
				{$t('Showing up to 20 workspaces. Type to narrow the search.')}
			</p>
			<label class="grid grid-cols-1 gap-1"
				>{$t('Reason (at least 10 characters)')}<textarea
					class="input"
					bind:value={reason}
					minlength="10"
					maxlength="1000"
					disabled={busyId !== '' || inspectionUnavailable}></textarea></label
			>
			<Button
				type="button"
				disabled={busyId !== '' || inspectionUnavailable || reason.trim().length < 10 || !targetId}
				onclick={() => void inspect()}>{$t('Inspect Items once')}</Button
			>
			{#if inspection && !inspectionUnavailable}<aside
					class="grid min-w-0 grid-cols-1 gap-2 rounded-md bg-warning-100-900 p-4"
				>
					<strong>{$t('BREAK GLASS')}</strong><span>{$t('Reason:')} {inspectionReason}</span>
					<span>{$t('Scope: Workspace')} {inspectionWorkspaceId} · {$t('Item list read-only')}</span
					>
					<span>{$t('Single response; no continuing access is granted')}</span>
					{#each inspection as item (item.id)}<div
							class="min-w-0 border-t border-surface-400 pt-2 dark:border-surface-700"
						>
							<RichText html={item.title_html} /><small class="block text-surface-600-400"
								>{item.authors.map((author) => author.full_name).join('; ')} · {item.publication_date ??
									''}</small
							>
						</div>{:else}<p>{$t('No Items found.')}</p>{/each}
				</aside>{/if}
		</div>
	</details>
</section>
