<script lang="ts">
	import { resolve } from '$app/paths';
	import { createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { Dialog } from 'bits-ui';
	import { apiRequest, type ProjectSummary } from '$lib/api/client';
	import Icon from '$lib/design/Icon.svelte';
	import { domainLabel } from '$lib/domain-labels';
	import { t } from '$lib/i18n';

	type JoinableProject = Omit<ProjectSummary, 'role'>;
	let createOpen = $state(false);
	let name = $state('');
	let description = $state('');
	let visibility = $state<'private' | 'public'>('private');
	let busy = $state(false);
	let error = $state('');
	const queryClient = useQueryClient();
	const projects = createQuery(() => ({
		queryKey: ['projects'],
		queryFn: () => apiRequest<ProjectSummary[]>('/projects')
	}));
	const joinable = createQuery(() => ({
		queryKey: ['projects', 'joinable'],
		queryFn: () => apiRequest<JoinableProject[]>('/projects/joinable')
	}));

	async function refresh() {
		await Promise.all([
			queryClient.invalidateQueries({ queryKey: ['projects'] }),
			queryClient.invalidateQueries({ queryKey: ['dashboard'] })
		]);
	}

	async function createProject() {
		busy = true;
		error = '';
		try {
			await apiRequest('/projects', { method: 'POST', body: { name, description, visibility } });
			name = '';
			description = '';
			visibility = 'private';
			createOpen = false;
			await refresh();
		} catch (reason) {
			error = reason instanceof Error ? reason.message : $t('Unable to create Project');
		} finally {
			busy = false;
		}
	}

	async function join(projectId: string) {
		busy = true;
		error = '';
		try {
			await apiRequest(`/projects/${projectId}/join`, { method: 'POST' });
			await refresh();
		} catch (reason) {
			error = reason instanceof Error ? reason.message : $t('Unable to join Project');
		} finally {
			busy = false;
		}
	}
</script>

<div class="workspace-header">
	<div>
		<p class="eyebrow">{$t('Collaboration')}</p>
		<h1>{$t('Projects')}</h1>
		<p class="muted">{$t('Shared collections with explicit membership and roles.')}</p>
	</div>
	<Dialog.Root bind:open={createOpen}>
		<Dialog.Trigger class="button button-primary flex items-center gap-2"
			><Icon name="plus" /> {$t('New Project')}</Dialog.Trigger
		>
		<Dialog.Portal>
			<Dialog.Overlay class="fixed inset-0 z-70 bg-[#07120d]/45 backdrop-blur-[2px]" />
			<Dialog.Content
				class="fixed top-1/2 left-1/2 z-71 w-[min(34rem,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 rounded-xl border border-line bg-raised p-5 shadow-2xl"
			>
				<div class="workspace-header">
					<div><Dialog.Title class="text-xl font-bold">{$t('Create Project')}</Dialog.Title></div>
					<Dialog.Close
						class="grid size-9 cursor-pointer place-items-center rounded-md hover:bg-muted-surface"
						aria-label={$t('Close')}><Icon name="close" /></Dialog.Close
					>
				</div>
				<form
					class="stack"
					onsubmit={(event) => {
						event.preventDefault();
						void createProject();
					}}
				>
					<label class="stack gap-1"
						>{$t('Name')}<input class="field" bind:value={name} required /></label
					>
					<label class="stack gap-1"
						>{$t('Description')}<textarea class="field min-h-28" bind:value={description}
						></textarea></label
					>
					<label class="stack gap-1"
						>{$t('Visibility')}<select class="field" bind:value={visibility}
							><option value="private">{$t('Private')}</option><option value="public"
								>{$t('Public')}</option
							></select
						></label
					>
					<p class="muted text-sm">
						{visibility === 'public'
							? $t('Any signed-in User can discover and join this Project.')
							: $t('Only invited members can access this Project.')}
					</p>
					<button class="button button-primary" disabled={busy}>{$t('Create Project')}</button>
				</form>
			</Dialog.Content>
		</Dialog.Portal>
	</Dialog.Root>
</div>

{#if error}<p class="error" role="alert">{error}</p>{/if}

<div class="grid gap-5 xl:grid-cols-[minmax(0,2fr)_minmax(18rem,1fr)]">
	<section class="panel list-panel mt-0">
		<h2>{$t('Your Projects')}</h2>
		{#if projects.isPending}<p class="muted">{$t('Loading Projects…')}</p>
		{:else if projects.isError}<p class="error">{$t('Unable to load Projects.')}</p>
		{:else}{#each projects.data ?? [] as project (project.id)}
				<a
					class="item-row group rounded-lg px-2 hover:bg-muted-surface"
					href={resolve('/(app)/projects/[projectId]', { projectId: project.id })}
				>
					<div class="flex items-center justify-between gap-3">
						<strong class="group-hover:text-accent-strong">{project.name}</strong>
						<span class="badge">{$t(project.state === 'archived' ? 'Archived' : 'Active')}</span>
					</div>
					{#if project.description}<span class="text-sm text-secondary">{project.description}</span
						>{/if}
					<span class="muted text-sm"
						>{$t(domainLabel(project.role))} · {project.item_count}
						{$t('Items')} · {$t(project.visibility === 'public' ? 'Public' : 'Private')}</span
					>
				</a>
			{:else}<p class="muted">{$t('No Projects yet.')}</p>{/each}{/if}
	</section>
	<aside class="panel list-panel mt-0">
		<h2>{$t('Public Projects')}</h2>
		<p class="muted text-sm">{$t('Join open research collections from this instance.')}</p>
		{#each joinable.data ?? [] as project (project.id)}
			<div class="item-row">
				<strong>{project.name}</strong>
				{#if project.description}<span class="text-sm text-secondary">{project.description}</span
					>{/if}
				<div class="flex items-center justify-between gap-2">
					<span class="muted text-sm">{project.item_count} {$t('Items')}</span>
					<button class="button" disabled={busy} onclick={() => join(project.id)}
						>{$t('Join')}</button
					>
				</div>
			</div>
		{:else}<p class="muted">{$t('No public Projects are available to join.')}</p>{/each}
	</aside>
</div>
