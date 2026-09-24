<script lang="ts">
	import { createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { apiRequest } from '$lib/api/client';
	import { apiErrorMessage } from '$lib/api/errors';
	import Button from '$lib/design/Button.svelte';
	import Notice from '$lib/design/Notice.svelte';
	import RichText from '$lib/design/RichText.svelte';
	import { adminWorkspacesQuery } from '$lib/features/admin/queries';
	import { getAdminFilters } from '$lib/features/admin/filters';
	import { t } from '$lib/i18n';
	import { domainLabel } from '$lib/domain-labels';
	import type { components } from '$lib/api/schema';

	const { filters } = getAdminFilters();
	const queryClient = useQueryClient();
	const workspaces = createQuery(() => adminWorkspacesQuery(filters()));
	let error = $state('');
	let busyId = $state('');
	let targetId = $state('');
	let reason = $state('');
	let inspection = $state<components['schemas']['ItemSearchView'][] | undefined>();
	let inspectionReason = $state('');
	let inspectionWorkspaceId = $state('');

	async function govern(workspaceId: string, operation: 'suspend' | 'recover') {
		busyId = workspaceId;
		error = '';
		try {
			if (operation === 'suspend')
				await apiRequest('POST', '/admin/workspaces/{workspace_id}/suspend', {
					params: { path: { workspace_id: workspaceId } }
				});
			else
				await apiRequest('POST', '/admin/workspaces/{workspace_id}/recover', {
					params: { path: { workspace_id: workspaceId } }
				});
			await Promise.all([
				workspaces.refetch(),
				queryClient.invalidateQueries({ queryKey: ['admin'] })
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
				'Instance administrators can suspend or recover Workspace governance. This does not grant ordinary content access.'
			)}
		</p>
	</header>
	{#if error}<Notice variant="error">{error}</Notice>{/if}
	{#if workspaces.isPending}<p>{$t('Loading workspaces…')}</p>{:else if workspaces.data?.length}<div
			class="grid grid-cols-1 gap-3"
		>
			{#each workspaces.data as workspace (workspace.id)}<article
					class="flex flex-wrap items-center justify-between gap-3 rounded-container border border-surface-300-700 p-4"
				>
					<div>
						<strong>{workspace.name}</strong>
						<p class="text-xs text-surface-600-400">
							{workspace.id} · {$t(domainLabel(workspace.state))} · {$t('owner')}
							{workspace.owner_id}{workspace.governance_suspended_at
								? ` · ${$t('suspended')} ${new Date(workspace.governance_suspended_at).toLocaleString()}`
								: ''}
						</p>
					</div>
					<div class="flex gap-2">
						{#if workspace.governance_suspended_at}<Button
								size="sm"
								disabled={busyId !== ''}
								onclick={() => void govern(workspace.id, 'recover')}>{$t('Recover')}</Button
							>{:else}<Button
								size="sm"
								variant="tonal"
								disabled={busyId !== ''}
								onclick={() => void govern(workspace.id, 'suspend')}
								>{$t('Suspend governance')}</Button
							>{/if}
					</div>
				</article>{/each}
		</div>{:else}<p>{$t('No workspaces.')}</p>{/if}
	<section
		class="border-warning-500-300 grid max-w-3xl grid-cols-1 gap-3 rounded-container border p-5"
	>
		<h3 class="text-xl font-semibold">{$t('BREAK GLASS · read-only item inspection')}</h3>
		<p>
			{$t(
				'Current backend MVP requires a reason for each read request. This response is not a durable access grant; it has no persistent scope, expiry, or revocation endpoint.'
			)}
		</p>
		<label class="grid grid-cols-1 gap-1"
			>{$t('Target Workspace')}<select class="input" bind:value={targetId}
				><option value="">{$t('Choose a Workspace')}</option
				>{#each workspaces.data ?? [] as workspace (workspace.id)}<option value={workspace.id}
						>{workspace.name}</option
					>{/each}</select
			></label
		>
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
				><span>{$t('Expiration: single response; no continuing access is granted')}</span
				>{#each inspection as item (item.id)}<div class="border-surface-400-700 border-t pt-2">
						<RichText html={item.title_html} /><small class="block text-surface-600-400"
							>{item.authors ?? ''} · {item.publication_date ?? ''}</small
						>
					</div>{:else}<p>{$t('No Items found.')}</p>{/each}
			</aside>{/if}
	</section>
</section>
