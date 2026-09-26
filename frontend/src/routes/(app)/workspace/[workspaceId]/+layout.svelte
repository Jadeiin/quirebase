<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { onWorkspaceConflict, onWorkspaceUnavailable } from '$lib/api/client';
	import { workspaceKeys } from '$lib/workspaces/keys';
	import WorkspaceProvider from '$lib/workspaces/WorkspaceProvider.svelte';
	import { workspaceListQuery, workspaceQuery } from '$lib/workspaces/queries';
	import { clearDefaultWorkspacePreference } from '$lib/workspaces/preference';
	import { apiErrorMessage } from '$lib/api/errors';
	import Notice from '$lib/design/Notice.svelte';
	import { t } from '$lib/i18n';

	let { children } = $props();
	const workspaceId = $derived(page.params.workspaceId ?? '');
	const workspace = createQuery(() => workspaceQuery(workspaceId));
	const workspaceList = createQuery(() => workspaceListQuery());
	const queryClient = useQueryClient();
	let recoveryStarted = $state(false);
	let unavailable = $state(false);
	let checkedWorkspaceError = $state<unknown>();

	onMount(() => {
		const unregisterUnavailable = onWorkspaceUnavailable((failedWorkspaceId) => {
			if (failedWorkspaceId !== workspaceId || recoveryStarted) return;
			recoveryStarted = true;
			void workspaceList.refetch().then((result) => {
				if (result.isError) {
					recoveryStarted = false;
					return;
				}
				const stillAvailable = result.data?.some((candidate) => candidate.id === workspaceId);
				if (!stillAvailable) {
					clearDefaultWorkspacePreference();
					unavailable = true;
					void goto(resolve('/workspace'), { replaceState: true });
				} else {
					recoveryStarted = false;
				}
			});
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
		if (!workspace.isError) {
			checkedWorkspaceError = undefined;
			return;
		}
		const currentError = workspace.error;
		if (recoveryStarted || checkedWorkspaceError === currentError) return;
		checkedWorkspaceError = currentError;
		recoveryStarted = true;
		void workspaceList.refetch().then((result) => {
			if (result.isError) {
				recoveryStarted = false;
				return;
			}
			const stillAvailable = result.data?.some((candidate) => candidate.id === workspaceId);
			if (!stillAvailable) clearDefaultWorkspacePreference();
			unavailable = !stillAvailable;
			if (!stillAvailable) void goto(resolve('/workspace'), { replaceState: true });
		});
	});
</script>

{#if workspace.isPending}<p class="text-surface-600-400">{$t('Loading workspace…')}</p>
{:else if workspace.isError}<Notice variant="error"
		>{unavailable
			? $t('This workspace is unavailable. Choose another workspace.')
			: apiErrorMessage(workspace.error, $t('Unable to load workspace.'))}</Notice
	>
{:else}
	{#if workspace.data?.governance_suspended}<Notice variant="warning"
			>{$t(
				'Workspace governance is suspended. Content is read only until an instance administrator recovers this Workspace.'
			)}</Notice
		>{:else if workspace.data?.state === 'archived'}<Notice
			>{$t(
				'Archived workspace · read-only content. Workspace governance actions remain available according to your capabilities.'
			)}</Notice
		>{/if}
	{#key workspaceId}<WorkspaceProvider {workspaceId} view={workspace.data}
			>{@render children()}</WorkspaceProvider
		>{/key}
{/if}
