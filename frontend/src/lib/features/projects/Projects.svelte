<script lang="ts">
	import { resolve } from '$app/paths';
	import { Dialog, Portal } from '@skeletonlabs/skeleton-svelte';
	import { createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { apiRequest } from '$lib/api/client';
	import { apiErrorMessage } from '$lib/api/errors';
	import Badge from '$lib/design/Badge.svelte';
	import Button from '$lib/design/Button.svelte';
	import Notice from '$lib/design/Notice.svelte';
	import DialogCloseButton from '$lib/design/DialogCloseButton.svelte';
	import DialogTriggerButton from '$lib/design/DialogTriggerButton.svelte';
	import Icon from '$lib/design/Icon.svelte';
	import Panel from '$lib/design/Panel.svelte';
	import SectionHeader from '$lib/design/SectionHeader.svelte';
	import { domainLabel } from '$lib/domain-labels';
	import { invalidateLibrary, invalidateProject } from '$lib/query/invalidation';
	import { joinableProjectsQuery, projectListQuery } from '$lib/features/projects/queries';
	import { t } from '$lib/i18n';
	import ItemRow from '$lib/design/ItemRow.svelte';

	let createOpen = $state(false);
	let name = $state('');
	let description = $state('');
	let visibility = $state<'private' | 'public'>('private');
	let busy = $state(false);
	let error = $state('');
	const queryClient = useQueryClient();
	const projects = createQuery(() => projectListQuery());
	const joinable = createQuery(() => joinableProjectsQuery());

	async function refresh() {
		await Promise.all([invalidateProject(queryClient), invalidateLibrary(queryClient)]);
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
			error = apiErrorMessage(reason, $t('Unable to create Project'));
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
			error = apiErrorMessage(reason, $t('Unable to join Project'));
		} finally {
			busy = false;
		}
	}
</script>

<SectionHeader>
	<div>
		<p class="mb-1 text-sm font-medium text-primary-700-300">{$t('Collaboration')}</p>
		<h1>{$t('Projects')}</h1>
		<p class="text-surface-600-400">
			{$t('Shared collections with explicit membership and roles.')}
		</p>
	</div>
	{#snippet actions()}
		<Dialog open={createOpen} onOpenChange={(details) => (createOpen = details.open)}>
			<DialogTriggerButton><Icon name="plus" /> {$t('New Project')}</DialogTriggerButton>
			<Portal>
				<Dialog.Backdrop class="fixed inset-0 z-70 bg-surface-950/45 backdrop-blur-[2px]" />
				<Dialog.Positioner class="fixed inset-0 z-71 grid grid-cols-1 place-items-center p-4">
					<Dialog.Content
						class="w-full max-w-lg rounded-container border border-surface-300-700 bg-surface-50-950 p-5 shadow-2xl"
					>
						<SectionHeader>
							<Dialog.Title class="text-xl font-bold">{$t('Create Project')}</Dialog.Title>
							{#snippet actions()}
								<DialogCloseButton />
							{/snippet}
						</SectionHeader>
						<form
							class="grid grid-cols-1 gap-3"
							onsubmit={(event) => {
								event.preventDefault();
								void createProject();
							}}
						>
							<label class="grid grid-cols-1 gap-1"
								>{$t('Name')}<input class="input" bind:value={name} required /></label
							>
							<label class="grid grid-cols-1 gap-1"
								>{$t('Description')}<textarea class="textarea min-h-28" bind:value={description}
								></textarea></label
							>
							<label class="grid grid-cols-1 gap-1"
								>{$t('Visibility')}<select class="select" bind:value={visibility}
									><option value="private">{$t('Private')}</option><option value="public"
										>{$t('Public')}</option
									></select
								></label
							>
							<p class="text-sm text-surface-600-400">
								{visibility === 'public'
									? $t('Any signed-in User can discover and join this Project.')
									: $t('Only invited members can access this Project.')}
							</p>
							<Button variant="filled" disabled={busy}>{$t('Create Project')}</Button>
						</form>
					</Dialog.Content>
				</Dialog.Positioner>
			</Portal>
		</Dialog>
	{/snippet}
</SectionHeader>

{#if error}<Notice variant="error">{error}</Notice>{/if}

<div class="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,2fr)_minmax(18rem,1fr)]">
	<Panel>
		<h2>{$t('Your Projects')}</h2>
		{#if projects.isPending}<p class="text-surface-600-400">{$t('Loading Projects…')}</p>
		{:else if projects.isError}<p class="text-error-700-300">{$t('Unable to load Projects.')}</p>
		{:else}{#each projects.data ?? [] as project (project.id)}
				<ItemRow
					as="a"
					class="group rounded-lg px-2 hover:bg-surface-200-800"
					href={resolve('/(app)/projects/[projectId]', { projectId: project.id })}
				>
					<div class="flex items-center justify-between gap-3">
						<strong class="group-hover:text-primary-800-200">{project.name}</strong>
						<Badge>{$t(project.state === 'archived' ? 'Archived' : 'Active')}</Badge>
					</div>
					{#if project.description}<span class="text-sm text-surface-700-300"
							>{project.description}</span
						>{/if}
					<span class="text-sm text-surface-600-400"
						>{$t(domainLabel(project.role))} · {project.item_count}
						{$t('Items')} · {$t(project.visibility === 'public' ? 'Public' : 'Private')}</span
					>
				</ItemRow>
			{:else}<p class="text-surface-600-400">{$t('No Projects yet.')}</p>{/each}{/if}
	</Panel>
	<Panel as="aside">
		<h2>{$t('Public Projects')}</h2>
		<p class="text-sm text-surface-600-400">
			{$t('Join open research collections from this instance.')}
		</p>
		{#each joinable.data ?? [] as project (project.id)}
			<ItemRow>
				<strong>{project.name}</strong>
				{#if project.description}<span class="text-sm text-surface-700-300"
						>{project.description}</span
					>{/if}
				<div class="flex items-center justify-between gap-2">
					<span class="text-sm text-surface-600-400">{project.item_count} {$t('Items')}</span>
					<Button disabled={busy} onclick={() => join(project.id)}>{$t('Join')}</Button>
				</div>
			</ItemRow>
		{:else}<p class="text-surface-600-400">
				{$t('No public Projects are available to join.')}
			</p>{/each}
	</Panel>
</div>
