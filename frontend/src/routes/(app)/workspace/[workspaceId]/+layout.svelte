<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { ApiError, onWorkspaceConflict, onWorkspaceUnavailable } from '#lib/api/client.js';
	import { workspaceKeys } from '#lib/workspaces/keys.js';
	import WorkspaceProvider from '#lib/workspaces/WorkspaceProvider.svelte';
	import { workspaceListQuery, workspaceQuery } from '#lib/workspaces/queries.js';
	import { clearDefaultWorkspacePreference } from '#lib/workspaces/preference.js';
	import { apiErrorMessage } from '#lib/api/errors.js';
	import Notice from '#lib/design/Notice.svelte';
	import { t } from '#lib/i18n.js';

	let { children } = $props();
	const workspaceId = $derived(page.params.workspaceId ?? '');
	const workspace = createQuery(() => workspaceQuery(workspaceId));
	const workspaceList = createQuery(() => workspaceListQuery());
	const queryClient = useQueryClient();
	let recoveryStarted = $state(false);
	let unavailable = $state(false);
	let checkedWorkspaceError = $state<unknown>();

	async function recover() {
		if (recoveryStarted) return;
		recoveryStarted = true;
		try {
			const [list, current] = await Promise.all([workspaceList.refetch(), workspace.refetch()]);
			if (list.isError) return;
			if (current.isError) {
				if (!(current.error instanceof ApiError) || current.error.code !== 'workspace_unavailable')
					return;
				clearDefaultWorkspacePreference();
				unavailable = true;
				void goto(resolve('workspace'), { replace: true });
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
			void Promise.all([
				queryClient.invalidateQueries({ queryKey: workspaceKeys.root(workspaceId) }),
				queryClient.invalidateQueries({ queryKey: workspaceKeys.list() })
			]);
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

{#if workspace.isPending}<p class="text-surface-600-400">{$t('Loading workspace…')}</p>
{:else if workspace.isError}<Notice variant="error"
		>{unavailable
			? $t('This workspace is unavailable. Choose another workspace.')
			: apiErrorMessage(workspace.error, $t('Unable to load workspace.'))}</Notice
	>
{:else}
	{#if workspace.data?.governance_frozen}
		<Notice variant="warning"
			>{$t(
				'Workspace writes are frozen. Content is read only until an instance administrator unfreezes this Workspace.'
			)}</Notice
		>
	{:else if workspace.data?.state === 'archived'}
		<Notice
			>{$t(
				'Archived workspace · read-only content. Workspace governance actions remain available according to policy.'
			)}</Notice
		>
	{/if}

	{#key workspaceId}
		<WorkspaceProvider {workspaceId} view={workspace.data}>{@render children()}</WorkspaceProvider>
	{/key}
{/if}
