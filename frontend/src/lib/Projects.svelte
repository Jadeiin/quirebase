<script lang="ts">
	import { resolve } from '$app/paths';
	import { Dialog, Portal } from '@skeletonlabs/skeleton-svelte';
	import { createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { apiRequest } from '$lib/api/client';
	import Icon from '$lib/design/Icon.svelte';
	import { domainLabel } from '$lib/domain-labels';
	import { t } from '$lib/i18n';

	let createOpen = $state(false);
	let name = $state('');
	let description = $state('');
	let visibility = $state<'private' | 'public'>('private');
	let busy = $state(false);
	let error = $state('');
	const queryClient = useQueryClient();
	const projects = createQuery(() => ({
		queryKey: ['projects'],
		queryFn: () => apiRequest('GET', '/projects')
	}));
	const joinable = createQuery(() => ({
		queryKey: ['projects', 'joinable'],
		queryFn: () => apiRequest('GET', '/projects/joinable')
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
			await apiRequest('POST', '/projects', { body: { name, description, visibility } });
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
			await apiRequest('POST', '/projects/{project_id}/join', {
				params: { path: { project_id: projectId } }
			});
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
		<p class="text-surface-600">{$t('Shared collections with explicit membership and roles.')}</p>
	</div>
	<Dialog open={createOpen} onOpenChange={(details) => (createOpen = details.open)}>
		<Dialog.Trigger class="btn flex items-center gap-2 preset-filled-primary-700-300 font-semibold"
			><Icon name="plus" /> {$t('New Project')}</Dialog.Trigger
		>
		<Portal>
			<Dialog.Backdrop class="fixed inset-0 z-70 bg-surface-950/45 backdrop-blur-[2px]" />
			<Dialog.Positioner class="fixed inset-0 z-71 grid place-items-center p-4">
				<Dialog.Content
					class="w-full max-w-lg rounded-container border border-surface-300 bg-surface-50 p-5 shadow-2xl"
				>
					<div class="workspace-header">
						<div><Dialog.Title class="text-xl font-bold">{$t('Create Project')}</Dialog.Title></div>
						<Dialog.CloseTrigger class="btn-icon preset-tonal-surface" aria-label={$t('Close')}
							><Icon name="close" /></Dialog.CloseTrigger
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
							>{$t('Name')}<input class="input" bind:value={name} required /></label
						>
						<label class="stack gap-1"
							>{$t('Description')}<textarea class="textarea min-h-28" bind:value={description}
							></textarea></label
						>
						<label class="stack gap-1"
							>{$t('Visibility')}<select class="select" bind:value={visibility}
								><option value="private">{$t('Private')}</option><option value="public"
									>{$t('Public')}</option
								></select
							></label
						>
						<p class="text-sm text-surface-600">
							{visibility === 'public'
								? $t('Any signed-in User can discover and join this Project.')
								: $t('Only invited members can access this Project.')}
						</p>
						<button class="btn preset-filled-primary-700-300 font-semibold" disabled={busy}
							>{$t('Create Project')}</button
						>
					</form>
				</Dialog.Content>
			</Dialog.Positioner>
		</Portal>
	</Dialog>
</div>

{#if error}<p class="text-error-700" role="alert">{error}</p>{/if}

<div class="grid gap-5 xl:grid-cols-[minmax(0,2fr)_minmax(18rem,1fr)]">
	<section class="list-panel mt-0 card border border-surface-300 bg-surface-50 p-5 shadow-sm">
		<h2>{$t('Your Projects')}</h2>
		{#if projects.isPending}<p class="text-surface-600">{$t('Loading Projects…')}</p>
		{:else if projects.isError}<p class="text-error-700">{$t('Unable to load Projects.')}</p>
		{:else}{#each projects.data ?? [] as project (project.id)}
				<a
					class="item-row group rounded-lg px-2 hover:bg-surface-200"
					href={resolve('/(app)/projects/[projectId]', { projectId: project.id })}
				>
					<div class="flex items-center justify-between gap-3">
						<strong class="group-hover:text-primary-800">{project.name}</strong>
						<span class="badge preset-tonal-surface"
							>{$t(project.state === 'archived' ? 'Archived' : 'Active')}</span
						>
					</div>
					{#if project.description}<span class="text-sm text-surface-700"
							>{project.description}</span
						>{/if}
					<span class="text-sm text-surface-600"
						>{$t(domainLabel(project.role))} · {project.item_count}
						{$t('Items')} · {$t(project.visibility === 'public' ? 'Public' : 'Private')}</span
					>
				</a>
			{:else}<p class="text-surface-600">{$t('No Projects yet.')}</p>{/each}{/if}
	</section>
	<aside class="list-panel mt-0 card border border-surface-300 bg-surface-50 p-5 shadow-sm">
		<h2>{$t('Public Projects')}</h2>
		<p class="text-sm text-surface-600">
			{$t('Join open research collections from this instance.')}
		</p>
		{#each joinable.data ?? [] as project (project.id)}
			<div class="item-row">
				<strong>{project.name}</strong>
				{#if project.description}<span class="text-sm text-surface-700">{project.description}</span
					>{/if}
				<div class="flex items-center justify-between gap-2">
					<span class="text-sm text-surface-600">{project.item_count} {$t('Items')}</span>
					<button
						class="btn preset-tonal-surface font-semibold"
						disabled={busy}
						onclick={() => join(project.id)}>{$t('Join')}</button
					>
				</div>
			</div>
		{:else}<p class="text-surface-600">{$t('No public Projects are available to join.')}</p>{/each}
	</aside>
</div>
