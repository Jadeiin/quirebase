<script lang="ts">
	import { resolve } from '$app/paths';
	import { goto } from '$app/navigation';
	import { Dialog, Portal } from '@skeletonlabs/skeleton-svelte';
	import { createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { apiErrorMessage } from '$lib/api/errors';
	import Badge from '$lib/design/Badge.svelte';
	import Button from '$lib/design/Button.svelte';
	import DialogCloseButton from '$lib/design/DialogCloseButton.svelte';
	import DialogTriggerButton from '$lib/design/DialogTriggerButton.svelte';
	import Icon from '$lib/design/Icon.svelte';
	import ItemRow from '$lib/design/ItemRow.svelte';
	import Notice from '$lib/design/Notice.svelte';
	import Panel from '$lib/design/Panel.svelte';
	import SectionHeader from '$lib/design/SectionHeader.svelte';
	import { domainLabel } from '$lib/domain-labels';
	import { projectListQuery, joinableProjectsQuery } from '$lib/features/projects/queries';
	import { invalidateProject } from '$lib/query/invalidation';
	import { t } from '$lib/i18n';
	import { getWorkspaceContext } from '$lib/workspaces/context.svelte';
	import { workspaceHref } from '$lib/workspaces/href';

	const workspace = getWorkspaceContext();
	const workspaceId = workspace.workspaceId;
	const queryClient = useQueryClient();
	const projects = createQuery(() => projectListQuery(workspaceId));
	const joinable = createQuery(() => joinableProjectsQuery(workspaceId));
	const myProjects = $derived((projects.data ?? []).filter((project) => project.is_member));
	const managedProjects = $derived(
		(projects.data ?? []).filter(
			(project) => project.visibility === 'managed' && !project.is_member
		)
	);
	const archivedOpenProjects = $derived(
		(projects.data ?? []).filter(
			(project) =>
				project.visibility === 'open' && project.state === 'archived' && !project.is_member
		)
	);

	let createOpen = $state(false);
	let name = $state('');
	let description = $state('');
	let visibility = $state<'workspace' | 'open' | 'managed'>('workspace');
	let busy = $state(false);
	let error = $state('');

	async function refresh() {
		await invalidateProject(queryClient, workspaceId);
	}

	async function createProject() {
		busy = true;
		error = '';
		try {
			const created = await workspace.api.request('POST', '/workspaces/{workspace_id}/projects', {
				body: { name: name.trim(), description, visibility }
			});
			name = '';
			description = '';
			visibility = 'workspace';
			createOpen = false;
			await refresh();
			await goto(resolve(workspaceHref(workspaceId, `projects/${created.id}`)));
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
			await workspace.api.request('POST', '/workspaces/{workspace_id}/projects/{project_id}/join', {
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
			{$t('Projects are research working contexts inside this Workspace.')}
		</p>
	</div>
	{#snippet actions()}
		{#if workspace.can('projects.create')}
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
								{#snippet actions()}<DialogCloseButton />{/snippet}
							</SectionHeader>
							<form
								class="grid grid-cols-1 gap-3"
								onsubmit={(event) => {
									event.preventDefault();
									void createProject();
								}}
							>
								<label class="grid grid-cols-1 gap-1"
									>{$t('Name')}<input
										class="input"
										bind:value={name}
										required
										maxlength="240"
									/></label
								>
								<label class="grid grid-cols-1 gap-1"
									>{$t('Description')}<textarea
										class="textarea min-h-28"
										bind:value={description}
										maxlength="2000"></textarea></label
								>
								<label class="grid grid-cols-1 gap-1"
									>{$t('Participation')}<select class="select" bind:value={visibility}
										><option value="workspace">{$t(domainLabel('workspace'))}</option><option
											value="open">{$t(domainLabel('open'))}</option
										>{#if workspace.can('projects.create_managed')}<option value="managed"
												>{$t(domainLabel('managed'))}</option
											>{/if}</select
									></label
								>
								<p class="text-sm text-surface-600-400">
									{#if visibility === 'workspace'}
										{$t('All active Workspace members participate in this Project.')}
									{:else if visibility === 'open'}
										{$t('Active Workspace members can choose to join or leave this Project.')}
									{:else}
										{$t(
											'Only Workspace owners and admins can create managed Projects and curate participation.'
										)}
										{$t(
											'Managed Projects are visible only to their participants and Workspace owners/admins.'
										)}
									{/if}
								</p>
								<Button variant="filled" disabled={busy || !name.trim()}
									>{$t('Create Project')}</Button
								>
							</form>
						</Dialog.Content>
					</Dialog.Positioner>
				</Portal>
			</Dialog>
		{/if}
	{/snippet}
</SectionHeader>

{#if error}<Notice variant="error">{error}</Notice>{/if}

<div class="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,2fr)_minmax(18rem,1fr)]">
	<Panel>
		<h2>{$t('Your Projects')}</h2>
		{#if projects.isPending}<p class="text-surface-600-400">{$t('Loading Projects…')}</p>
		{:else if projects.isError}<p class="text-error-700-300">{$t('Unable to load Projects.')}</p>
		{:else}{#each myProjects as project (project.id)}
				<ItemRow
					as="a"
					class="group rounded-lg px-2 hover:bg-surface-200-800"
					href={resolve(workspaceHref(workspaceId, `projects/${project.id}`))}
				>
					<div class="flex items-center justify-between gap-3">
						<strong class="group-hover:text-primary-800-200">{project.name}</strong>
						<Badge>{$t(domainLabel(project.state))}</Badge>
					</div>
					{#if project.description}<span class="text-sm text-surface-700-300"
							>{project.description}</span
						>{/if}
					<span class="text-sm text-surface-600-400"
						>{project.item_count} {$t('Items')} · {$t(domainLabel(project.visibility))}</span
					>
				</ItemRow>
			{:else}<p class="text-surface-600-400">{$t('No Projects yet.')}</p>{/each}{/if}
	</Panel>
	<Panel as="aside">
		<h2>{$t('Open Projects')}</h2>
		<p class="text-sm text-surface-600-400">
			{$t('Join an open research direction to add it to Your Projects.')}
		</p>
		{#if joinable.isPending}<p class="text-surface-600-400">{$t('Loading Projects…')}</p>
		{:else if joinable.isError}<p class="text-error-700-300">{$t('Unable to load Projects.')}</p>
		{:else}{#each joinable.data ?? [] as project (project.id)}
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
					{$t('No open Projects are available to join.')}
				</p>{/each}{/if}
	</Panel>
</div>

{#if managedProjects.length > 0}
	<Panel class="mt-5">
		<h2>{$t('Managed participation')}</h2>
		<p class="text-sm text-surface-600-400">
			{$t(
				'Managed Projects are visible to participants and Workspace owners/admins; Workspace owners/admins curate their participant lists.'
			)}
		</p>
		{#each managedProjects as project (project.id)}
			<ItemRow
				as="a"
				class="group rounded-lg px-2 hover:bg-surface-200-800"
				href={resolve(workspaceHref(workspaceId, `projects/${project.id}`))}
			>
				<strong class="group-hover:text-primary-800-200">{project.name}</strong>
				{#if project.description}<span class="text-sm text-surface-700-300"
						>{project.description}</span
					>{/if}
				<span class="text-sm text-surface-600-400"
					>{project.item_count} {$t('Items')} · {$t(domainLabel(project.state))}</span
				>
			</ItemRow>
		{/each}
	</Panel>
{/if}

{#if archivedOpenProjects.length > 0}
	<Panel class="mt-5">
		<h2>{$t('Archived Projects')}</h2>
		{#each archivedOpenProjects as project (project.id)}
			<ItemRow
				as="a"
				class="group rounded-lg px-2 hover:bg-surface-200-800"
				href={resolve(workspaceHref(workspaceId, `projects/${project.id}`))}
			>
				<strong class="group-hover:text-primary-800-200">{project.name}</strong>
				{#if project.description}<span class="text-sm text-surface-700-300"
						>{project.description}</span
					>{/if}
				<span class="text-sm text-surface-600-400">{project.item_count} {$t('Items')}</span>
			</ItemRow>
		{/each}
	</Panel>
{/if}
