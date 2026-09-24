<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { Menu, Portal } from '@skeletonlabs/skeleton-svelte';
	import { createQuery } from '@tanstack/svelte-query';
	import Icon from '$lib/design/Icon.svelte';
	import { domainLabel } from '$lib/domain-labels';
	import { t } from '$lib/i18n';
	import { workspaceHref } from '$lib/workspaces/href';
	import { workspaceListQuery } from '$lib/workspaces/queries';
	import { setDefaultWorkspacePreference } from '$lib/workspaces/preference';

	let {
		workspaceId,
		compact = false,
		mobile = false
	} = $props<{
		workspaceId?: string;
		compact?: boolean;
		mobile?: boolean;
	}>();

	const workspaces = createQuery(() => workspaceListQuery());
	const currentWorkspace = $derived(
		(workspaces.data ?? []).find((workspace) => workspace.id === workspaceId)
	);

	function openWorkspace(nextId: string) {
		if (nextId === workspaceId) return;
		setDefaultWorkspacePreference(nextId);
		void goto(resolve(workspaceHref(nextId)));
	}
</script>

<Menu positioning={{ placement: 'bottom-start', gutter: 8 }}>
	<Menu.Trigger
		class={`flex min-w-0 cursor-pointer items-center border-0 bg-transparent text-white transition-colors hover:bg-white/8 ${
			mobile
				? 'max-w-[calc(100vw-5rem)] gap-2 rounded-lg px-1.5 py-1'
				: compact
					? 'size-10 justify-center rounded-lg'
					: 'flex-1 gap-2.5 rounded-lg px-2 py-1.5 text-left'
		}`}
		aria-label={$t('Workspace')}
		title={compact ? $t('Workspace') : undefined}
	>
		<span
			class={`grid shrink-0 grid-cols-1 place-items-center rounded-xl bg-primary-50 font-serif font-extrabold text-primary-800 ${mobile ? 'size-7 text-base' : 'size-8 text-xl'}`}
			>Q</span
		>
		{#if !compact}
			<span class="grid min-w-0 flex-1 grid-cols-1 text-left leading-tight">
				<strong
					class={`${mobile ? 'text-sm' : 'text-[0.95rem]'} truncate font-extrabold tracking-tight`}
					>Quirebase</strong
				>
				<span class="truncate text-[0.68rem] text-surface-400">
					{currentWorkspace?.name ?? (workspaceId ? $t('Workspace') : $t('Choose workspace'))}
				</span>
			</span>
			<Icon name="chevron-down" size={15} />
		{/if}
	</Menu.Trigger>
	<Portal>
		<Menu.Positioner class="z-100">
			<Menu.Content
				class="max-h-[min(70vh,32rem)] min-w-60 overflow-y-auto rounded-container border border-surface-300-700 bg-surface-50-950 p-1 text-surface-900-100 shadow-xl"
			>
				<div class="px-2.5 py-1.5 text-xs font-bold tracking-wide text-surface-600-400 uppercase">
					{$t('Workspaces')}
				</div>
				{#if workspaces.isPending}
					<p class="px-2.5 py-2 text-sm text-surface-600-400">{$t('Loading workspaces…')}</p>
				{:else if workspaces.data?.length}
					{#each workspaces.data as workspace (workspace.id)}
						<Menu.Item
							value={`workspace-${workspace.id}`}
							class="flex cursor-pointer items-center gap-2 rounded-md px-2.5 py-2 text-sm outline-none data-[active=true]:bg-primary-50-950 data-[active=true]:text-primary-800-200 data-[highlighted]:bg-primary-50-950 data-[highlighted]:text-primary-800-200"
							data-active={workspace.id === workspaceId}
							onclick={() => openWorkspace(workspace.id)}
						>
							<span class="grid min-w-0 flex-1 grid-cols-1">
								<strong class="truncate font-medium">{workspace.name}</strong>
								<small class="text-xs text-surface-600-400"
									>{$t(domainLabel(workspace.current_role))}</small
								>
							</span>
							{#if workspace.id === workspaceId}<span aria-hidden="true">✓</span>{/if}
						</Menu.Item>
					{/each}
				{:else}
					<p class="px-2.5 py-2 text-sm text-surface-600-400">{$t('No workspaces available')}</p>
				{/if}
				<Menu.Separator class="m-1 h-px bg-surface-300-700" />
				<Menu.Item
					value="manage-workspaces"
					class="flex cursor-pointer items-center gap-2 rounded-md px-2.5 py-2 text-sm outline-none data-[highlighted]:bg-primary-50-950 data-[highlighted]:text-primary-800-200"
					onclick={() => goto(resolve('/workspace'))}
					><Icon name="panel" /> {$t('Manage workspaces')}</Menu.Item
				>
				{#if workspaceId}
					<Menu.Item
						value="workspace-settings"
						class="flex cursor-pointer items-center gap-2 rounded-md px-2.5 py-2 text-sm outline-none data-[highlighted]:bg-primary-50-950 data-[highlighted]:text-primary-800-200"
						onclick={() => goto(resolve(workspaceHref(workspaceId, 'settings')))}
						><Icon name="settings" /> {$t('Workspace settings')}</Menu.Item
					>
				{/if}
			</Menu.Content>
		</Menu.Positioner>
	</Portal>
</Menu>
