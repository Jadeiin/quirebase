<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { createQuery } from '@tanstack/svelte-query';
	import { onWorkspaceUnavailable } from '$lib/api/client';
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
	let recoveryStarted = $state(false);
	let unavailable = $state(false);

	onMount(() =>
		onWorkspaceUnavailable((failedWorkspaceId) => {
			if (failedWorkspaceId !== workspaceId || recoveryStarted) return;
			recoveryStarted = true;
			void workspaceList.refetch().then((result) => {
				const stillAvailable = result.data?.some((candidate) => candidate.id === workspaceId);
				if (!stillAvailable) {
					clearDefaultWorkspacePreference();
					unavailable = true;
					void goto(resolve('/workspace'), { replaceState: true });
				} else {
					recoveryStarted = false;
				}
			});
		})
	);

	$effect(() => {
		if (!workspace.isError || recoveryStarted) return;
		recoveryStarted = true;
		void workspaceList.refetch().then((result) => {
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
	{#if workspace.data?.state === 'archived'}<Notice
			>{$t(
				'Archived workspace · read-only content. Workspace governance actions remain available according to your capabilities.'
			)}</Notice
		>{/if}
	{#key workspaceId}<WorkspaceProvider {workspaceId} view={workspace.data}
			>{@render children()}</WorkspaceProvider
		>{/key}
{/if}
