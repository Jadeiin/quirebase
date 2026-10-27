<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { ApiError, onWorkspaceConflict, onWorkspaceUnavailable } from '#lib/api/client.js';
	import { invalidateWorkspaces } from '#lib/query/invalidation.js';
	import { reconcileWorkspaceAccessLoss } from '#lib/features/workspaces/access-loss.js';
	import { getSession } from '#lib/session.js';
	import WorkspaceProvider from '#lib/workspaces/WorkspaceProvider.svelte';
	import { workspaceListQuery, workspaceQuery } from '#lib/workspaces/queries.js';
	import {
		clearDefaultWorkspacePreference,
		defaultWorkspacePreference
	} from '#lib/workspaces/preference.js';
	import { isUnavailableReadError } from '#lib/api/query-state.js';
	import Notice from '#lib/design/Notice.svelte';
	import QueryError from '#lib/design/QueryError.svelte';
	import { t } from 'lingui-for-svelte/macro';

	let { children } = $props();
	const workspaceId = $derived(page.params.workspaceId ?? '');
	const workspace = createQuery(() => workspaceQuery(workspaceId));
	// Only recover() needs this list; WorkspaceMenu loads the directory for normal navigation.
	const workspaceList = createQuery(() => ({ ...workspaceListQuery(), enabled: false }));
	const queryClient = useQueryClient();
	const session = getSession().query;
	let recoveryStarted = $state(false);
	let unavailable = $state(false);
	let checkedWorkspaceError = $state<unknown>();

	async function recover() {
		if (recoveryStarted) return;
		recoveryStarted = true;
		const recoveringWorkspaceId = workspaceId;
		try {
			const [list, current] = await Promise.all([workspaceList.refetch(), workspace.refetch()]);
			if (list.isError) return;
			if (current.isError) {
				if (!(current.error instanceof ApiError) || current.error.code !== 'workspace_unavailable')
					return;
				if (defaultWorkspacePreference() === recoveringWorkspaceId)
					clearDefaultWorkspacePreference();
				if (workspaceId === recoveringWorkspaceId) {
					unavailable = true;
					await goto(resolve('workspace'), { replace: true });
				}
				// Remove projections after leaving the route, then refresh every directory
				// and menu scope so a lost response cannot leave revoked access selectable.
				await reconcileWorkspaceAccessLoss(
					queryClient,
					recoveringWorkspaceId,
					session.data?.user?.id ?? ''
				);
			} else {
				unavailable = false;
			}
		} finally {
			checkedWorkspaceError = workspace.error;
			recoveryStarted = false;
		}
	}

	onMount(() => {
		const unregisterUnavailable = onWorkspaceUnavailable((failedWorkspaceId) => {
			if (failedWorkspaceId === workspaceId) void recover();
		});
		const unregisterConflict = onWorkspaceConflict((failedWorkspaceId) => {
			if (failedWorkspaceId !== workspaceId) return;
			void invalidateWorkspaces(queryClient);
		});
		return () => {
			unregisterUnavailable();
			unregisterConflict();
		};
	});

	$effect(() => {
		if (workspace.isSuccess) {
			checkedWorkspaceError = undefined;
			return;
		}
		if (!workspace.isError) return;
		const currentError = workspace.error;
		if (recoveryStarted || checkedWorkspaceError === currentError) return;
		checkedWorkspaceError = currentError;
		void recover();
	});
</script>

{#if workspace.isError || (!workspace.isPending && workspace.data == null)}
	<QueryError
		message={unavailable
			? $t`This workspace is unavailable. Choose another workspace.`
			: $t`Unable to load workspace.`}
		busy={workspace.isFetching || recoveryStarted}
		onRetry={() => void recover()}
	/>
{/if}
{#if workspace.isPending && workspace.data == null}<p class="text-surface-600-400">
		{$t`Loading workspace…`}
	</p>
{:else if workspace.data && !isUnavailableReadError(workspace.error)}
	{#if workspace.data?.governance_frozen}
		<Notice variant="warning"
			>{$t`This Workspace is frozen and read only. An instance administrator can unfreeze it.`}</Notice
		>
	{:else if workspace.data?.state === 'archived'}
		<Notice>{$t`Archived Workspace · read-only content.`}</Notice>
	{/if}

	{#key workspaceId}
		<WorkspaceProvider {workspaceId} view={workspace.data}>{@render children()}</WorkspaceProvider>
	{/key}
{/if}
