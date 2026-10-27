<script lang="ts">
	import type { Snippet } from 'svelte';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { getWorkspaceContext } from '#lib/workspaces/context.svelte.js';
	import { workspaceHref } from '#lib/workspaces/href.js';
	import SectionTabs from '#lib/design/SectionTabs.svelte';
	import SectionTab from '#lib/design/SectionTab.svelte';
	import Badge from '#lib/design/Badge.svelte';
	import { domainLabel } from '#lib/domain-labels.js';
	import { t } from 'lingui-for-svelte/macro';

	let { children }: { children: Snippet } = $props();
	const workspace = getWorkspaceContext();
	const base = workspaceHref(workspace.workspaceId, 'settings');
	const advanced = $derived(
		workspace.can('workspace_maintenance.run') ||
			workspace.can('workspace.archive') ||
			workspace.can('workspace.restore') ||
			workspace.can('workspace.delete')
	);
</script>

<svelte:head><title>{$t`Workspace settings · Quirebase`}</title></svelte:head>
<section class="mx-auto grid w-full max-w-5xl grid-cols-1 gap-6">
	<header class="grid grid-cols-1 gap-2">
		<p class="line-clamp-2 text-sm font-semibold break-all text-primary-700-300">
			{workspace.view?.name}
		</p>
		<h1 class="text-3xl font-bold">{$t`Workspace settings`}</h1>
		<div class="flex flex-wrap items-center gap-2 text-sm text-surface-700-300">
			{#if workspace.role}<span>{$t`Your role:`} {$t(domainLabel(workspace.role))}</span>{/if}
			{#if workspace.view?.state}<Badge>{$t(domainLabel(workspace.view.state))}</Badge>{/if}
		</div>
	</header>
	<div>
		<SectionTabs label={$t`Workspace settings`}>
			<SectionTab href={resolve(base)} current={page.url.pathname === resolve(base)}
				>{$t`General`}</SectionTab
			>
			<SectionTab
				href={resolve(workspaceHref(workspace.workspaceId, 'settings/members'))}
				current={page.url.pathname.endsWith('/settings/members')}>{$t`Members`}</SectionTab
			>
			{#if workspace.can('workspace_invitation.read')}
				<SectionTab
					href={resolve(workspaceHref(workspace.workspaceId, 'settings/invitations'))}
					current={page.url.pathname.endsWith('/settings/invitations')}
					>{$t`Invitations`}</SectionTab
				>
			{/if}
			{#if advanced}<SectionTab
					href={resolve(workspaceHref(workspace.workspaceId, 'settings/advanced'))}
					current={page.url.pathname.endsWith('/settings/advanced')}>{$t`Advanced`}</SectionTab
				>{/if}
		</SectionTabs>
		{@render children()}
	</div>
</section>
