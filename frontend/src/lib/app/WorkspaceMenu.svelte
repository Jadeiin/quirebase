<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { Menu, Portal } from '@skeletonlabs/skeleton-svelte';
	import { createInfiniteQuery, createQuery } from '@tanstack/svelte-query';
	import Icon from '#lib/design/Icon.svelte';
	import Button from '#lib/design/Button.svelte';
	import { domainLabel } from '#lib/domain-labels.js';
	import { t } from '#lib/i18n.js';
	import { workspaceHref } from '#lib/workspaces/href.js';
	import { workspaceOptionsQuery, workspaceQuery } from '#lib/workspaces/queries.js';
	import { setDefaultWorkspacePreference } from '#lib/workspaces/preference.js';

	let {
		workspaceId,
		compact = false,
		mobile = false
	}: {
		workspaceId?: string;
		compact?: boolean;
		mobile?: boolean;
	} = $props();

	const workspaces = createInfiniteQuery(() => workspaceOptionsQuery());
	const current = createQuery(() => workspaceQuery(workspaceId ?? ''));
	const currentWorkspace = $derived(current.data);
	// Mirrors the visible text so the accessible name honours WCAG 2.5.3 (label in name).
	const contextLabel = $derived(
		currentWorkspace?.name ?? (workspaceId ? $t('Workspace') : $t('Choose workspace'))
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
		aria-label={compact ? `Quirebase ${contextLabel}` : undefined}
		title={compact ? $t('Workspace') : undefined}
	>
		<span
			aria-hidden="true"
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
					{contextLabel}
				</span>
			</span>
			<Icon name="chevron-down" size={15} />
		{/if}
	</Menu.Trigger>
	<Portal>
		<Menu.Positioner class="z-100">
			<Menu.Content
				class="max-h-[min(70vh,32rem)] w-72 max-w-[calc(100vw-2rem)] min-w-0 overflow-y-auto border-surface-300-700 p-1 shadow-xl"
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
							class="min-w-0 cursor-pointer justify-start gap-2 px-2.5 py-2 text-sm outline-none data-[active=true]:bg-primary-50-950 data-[active=true]:text-primary-800-200 data-[highlighted]:bg-primary-50-950 data-[highlighted]:text-primary-800-200"
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
				<Menu.Separator class="my-1 h-px bg-surface-300-700" />
				<Menu.Item
					value="manage-workspaces"
					class="min-w-0 cursor-pointer justify-start gap-2 px-2.5 py-2 text-sm outline-none data-[highlighted]:bg-primary-50-950 data-[highlighted]:text-primary-800-200"
					onclick={() => goto(resolve('workspace'))}
					><Icon name="panel" />{$t('Manage workspaces')}</Menu.Item
				>

				{#if workspaceId}
					<Menu.Item
						value="workspace-settings"
						class="min-w-0 cursor-pointer justify-start gap-2 px-2.5 py-2 text-sm outline-none data-[highlighted]:bg-primary-50-950 data-[highlighted]:text-primary-800-200"
						onclick={() => goto(resolve(workspaceHref(workspaceId, 'settings')))}
						><Icon name="settings" /> {$t('Workspace settings')}</Menu.Item
					>
				{/if}
				{#if workspaces.hasNextPage}<Button
						class="w-full"
						disabled={workspaces.isFetchingNextPage}
						onclick={() => void workspaces.fetchNextPage()}>{$t('Load more workspaces')}</Button
					>{/if}
			</Menu.Content>
		</Menu.Positioner>
	</Portal>
</Menu>
