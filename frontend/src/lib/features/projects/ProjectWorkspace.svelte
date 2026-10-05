<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { ApiError } from '#lib/api/client.js';
	import { apiErrorMessage } from '#lib/api/errors.js';
	import {
		can as isAllowed,
		canVariant as isVariantAllowed,
		type AuthorizationAction
	} from '#lib/authorization/can.js';
	import Button from '#lib/design/Button.svelte';
	import ItemRow from '#lib/design/ItemRow.svelte';
	import Notice from '#lib/design/Notice.svelte';
	import Panel from '#lib/design/Panel.svelte';
	import PromptDialog from '#lib/design/PromptDialog.svelte';
	import RichText from '#lib/design/RichText.svelte';
	import SectionHeader from '#lib/design/SectionHeader.svelte';
	import { domainLabel } from '#lib/domain-labels.js';
	import { projectDetailQuery } from '#lib/features/projects/queries.js';
	import { t } from '#lib/i18n.js';
	import { toaster } from '#lib/toaster.js';
	import { invalidateProject } from '#lib/query/invalidation.js';
	import { getWorkspaceContext } from '#lib/workspaces/context.svelte.js';
	import { workspaceHref } from '#lib/workspaces/href.js';
	import { workspaceKeys } from '#lib/workspaces/keys.js';

	let { projectId } = $props<{ projectId: string }>();
	const workspace = getWorkspaceContext();
	const workspaceId = workspace.workspaceId;
	const queryClient = useQueryClient();
	const detail = createQuery(() => projectDetailQuery(workspaceId, projectId));
	const project = $derived(detail.data);
	const discussions = createQuery(() => ({
		queryKey: workspaceKeys.projectDiscussions(workspaceId, projectId),
		enabled: Boolean(project),
		queryFn: ({ signal }: { signal: AbortSignal }) =>
			workspace.api.request('GET', '/workspaces/{workspace_id}/projects/{project_id}/discussions', {
				params: { path: { project_id: projectId } },
				signal
			})
	}));

	let error = $state('');
	let notice = $state('');
	let busy = $state(false);
	let username = $state('');
	let body = $state('');
	let settingsName = $state('');
	let settingsDescription = $state('');
	let settingsParticipation = $state<'workspace' | 'open' | 'managed'>('workspace');
	let deleteDialogOpen = $state(false);
	let moderationMessageId = $state<string | null>(null);
	let moderationDialogOpen = $state(false);

	$effect(() => {
		if (!project) return;
		settingsName = project.name;
		settingsDescription = project.description;
		settingsParticipation = project.participation as 'workspace' | 'open' | 'managed';
	});

	async function mutate(
		action: () => Promise<unknown>,
		success: string,
		reload = true,
		successToast = false
	): Promise<boolean> {
		busy = true;
		error = '';
		notice = '';
		try {
			await action();
			if (successToast) toaster.success({ title: success });
			else notice = success;
			if (reload) {
				await invalidateProject(queryClient, workspaceId);
			}
			return true;
		} catch (reason) {
			error = apiErrorMessage(reason, $t('Project action failed'));
			if (
				reason instanceof ApiError &&
				['project_lifecycle_error', 'project_member_conflict'].includes(reason.code)
			) {
				await invalidateProject(queryClient, workspaceId);
			} else {
				await detail.refetch();
			}
			return false;
		} finally {
			busy = false;
		}
	}

	function can(action: AuthorizationAction) {
		return isAllowed(project?.authorization, action);
	}

	function canVariant(action: AuthorizationAction, relation: string) {
		return isVariantAllowed(project?.authorization, action, relation);
	}

	async function saveSettings(event: SubmitEvent) {
		event.preventDefault();
		if (!canVariant('project.update', settingsParticipation)) return;
		await mutate(
			() =>
				workspace.api.request('PATCH', '/workspaces/{workspace_id}/projects/{project_id}', {
					params: { path: { project_id: projectId } },
					body: {
						name: settingsName.trim(),
						description: settingsDescription,
						participation: settingsParticipation
					}
				}),
			$t('Project settings saved')
		);
	}

	async function joinProject() {
		await mutate(
			() =>
				workspace.api.request('POST', '/workspaces/{workspace_id}/projects/{project_id}/join', {
					params: { path: { project_id: projectId } }
				}),
			$t('Joined Project')
		);
	}

	async function leaveProject() {
		await mutate(
			() =>
				workspace.api.request('POST', '/workspaces/{workspace_id}/projects/{project_id}/leave', {
					params: { path: { project_id: projectId } }
				}),
			$t('Left Project')
		);
	}

	async function addMember(event: SubmitEvent) {
		event.preventDefault();
		if (!username.trim()) return;
		const added = await mutate(
			() =>
				workspace.api.request('PUT', '/workspaces/{workspace_id}/projects/{project_id}/members', {
					params: { path: { project_id: projectId } },
					body: { username: username.trim() }
				}),
			$t('Project participant added')
		);
		if (added) username = '';
	}

	async function removeMember(userId: string) {
		await mutate(
			() =>
				workspace.api.request(
					'DELETE',
					'/workspaces/{workspace_id}/projects/{project_id}/members/{user_id}',
					{ params: { path: { project_id: projectId, user_id: userId } } }
				),
			$t('Project participant removed')
		);
	}

	async function changeState(action: 'archive' | 'restore') {
		await mutate(
			() =>
				workspace.api.request(
					'POST',
					`/workspaces/{workspace_id}/projects/{project_id}/${action}`,
					{ params: { path: { project_id: projectId } } }
				),
			$t(action === 'archive' ? 'Project archived' : 'Project restored')
		);
	}

	async function confirmDeleteProject(confirmation: string) {
		deleteDialogOpen = false;
		const deleted = await mutate(
			() =>
				workspace.api.request('DELETE', '/workspaces/{workspace_id}/projects/{project_id}', {
					params: { path: { project_id: projectId } },
					body: { confirmation }
				}),
			$t('Project deleted'),
			false
		);
		if (deleted) await goto(resolve(workspaceHref(workspaceId, 'projects')));
	}

	async function addDiscussion(event: SubmitEvent) {
		event.preventDefault();
		if (!body.trim()) return;
		const posted = await mutate(
			() =>
				workspace.api.request(
					'POST',
					'/workspaces/{workspace_id}/projects/{project_id}/discussions',
					{ params: { path: { project_id: projectId } }, body: { body: body.trim() } }
				),
			$t('Discussion posted'),
			true,
			true
		);
		if (posted) body = '';
	}

	async function deleteDiscussion(messageId: string) {
		if (
			!discussions.data?.some(
				(message) =>
					message.id === messageId &&
					message.mine &&
					isAllowed(message.authorization, 'project_discussion.delete')
			)
		)
			return;
		await mutate(
			() =>
				workspace.api.request(
					'DELETE',
					'/workspaces/{workspace_id}/projects/{project_id}/discussions/{message_id}',
					{ params: { path: { project_id: projectId, message_id: messageId } } }
				),
			$t('Discussion message deleted')
		);
	}

	async function moderateDiscussion(reason: string) {
		const messageId = moderationMessageId;
		if (
			!messageId ||
			!reason.trim() ||
			!discussions.data?.some(
				(message) =>
					message.id === messageId &&
					!message.mine &&
					isAllowed(message.authorization, 'project_discussion.delete')
			)
		)
			return;
		moderationDialogOpen = false;
		await mutate(
			() =>
				workspace.api.request(
					'POST',
					'/workspaces/{workspace_id}/projects/{project_id}/discussions/{message_id}/moderation',
					{
						params: { path: { project_id: projectId, message_id: messageId } },
						body: { reason: reason.trim() }
					}
				),
			$t('Discussion message moderated')
		);
	}
</script>

<section class="grid grid-cols-1 gap-6">
	<a
		class="text-sm text-primary-700-300 no-underline"
		href={resolve(workspaceHref(workspaceId, 'projects'))}>← {$t('Projects')}</a
	>
	{#if error}<Notice variant="error">{error}</Notice>{/if}
	{#if notice}<Notice>{notice}</Notice>{/if}
	{#if detail.isPending}<p>{$t('Loading Project…')}</p>
	{:else if detail.isError || !project}<Notice variant="error"
			>{$t('Unable to load Project.')}</Notice
		>
	{:else}
		<SectionHeader>
			<div>
				<p class="mb-1 text-sm text-primary-700-300">
					{$t(domainLabel(project.state))} · {$t(domainLabel(project.participation))} · {project.item_count}
					{$t('Items')}
				</p>
				<h1>{project.name}</h1>
				<p class="text-surface-600-400">{project.description || $t('No description')}</p>
			</div>
			{#snippet actions()}
				<div class="flex flex-wrap gap-2">
					{#if can('project_membership.join')}<Button
							disabled={busy}
							onclick={() => void joinProject()}>{$t('Join Project')}</Button
						>{/if}
					{#if can('project_membership.leave')}<Button
							variant="tonal"
							disabled={busy}
							onclick={() => void leaveProject()}>{$t('Leave Project')}</Button
						>{/if}
					<Button
						as="a"
						href={resolve(
							workspaceHref(workspaceId, `library?project=${encodeURIComponent(projectId)}`)
						)}>{$t('Open in Library')}</Button
					>
					{#if can('project.archive')}<Button
							variant="tonal"
							disabled={busy}
							onclick={() => void changeState('archive')}>{$t('Archive')}</Button
						>{:else if can('project.restore')}<Button
							disabled={busy}
							onclick={() => void changeState('restore')}>{$t('Restore')}</Button
						>{/if}
				</div>
			{/snippet}
		</SectionHeader>

		{#if can('project.update')}
			<Panel>
				<form class="grid grid-cols-1 gap-3 md:grid-cols-2" onsubmit={saveSettings}>
					<h2 class="text-xl font-semibold md:col-span-2">{$t('Project settings')}</h2>
					<label class="grid grid-cols-1 gap-1"
						>{$t('Name')}<input
							class="input"
							bind:value={settingsName}
							required
							maxlength="240"
						/></label
					>
					<label class="grid grid-cols-1 gap-1"
						>{$t('Participation')}<select class="select" bind:value={settingsParticipation}
							>{#if canVariant('project.update', 'workspace')}<option value="workspace"
									>{$t(domainLabel('workspace'))}</option
								>{/if}{#if canVariant('project.update', 'open')}<option value="open"
									>{$t(domainLabel('open'))}</option
								>{/if}{#if canVariant('project.update', 'managed')}<option value="managed"
									>{$t(domainLabel('managed'))}</option
								>{/if}</select
						></label
					>
					{#if settingsParticipation !== project.participation}
						<p class="text-sm text-surface-600-400 md:col-span-2">
							{#if settingsParticipation === 'workspace'}
								{$t('All active Workspace members will participate in this Project.')}
							{:else if settingsParticipation === 'managed'}
								{$t(
									'A managed Project starts with no participants; Workspace owners/admins can add them.'
								)}
							{:else if project.participation === 'workspace'}
								{$t(
									'Switching from Workspace-wide participation starts with you as the first participant.'
								)}
							{:else}
								{$t(
									'Switching between open and managed participation preserves current participants.'
								)}
							{/if}
						</p>
					{/if}
					<label class="grid grid-cols-1 gap-1 md:col-span-2"
						>{$t('Description')}<textarea class="textarea min-h-24" bind:value={settingsDescription}
						></textarea></label
					>
					<div class="flex flex-wrap gap-2 md:col-span-2">
						<Button
							disabled={busy ||
								!settingsName.trim() ||
								!canVariant('project.update', settingsParticipation)}
							>{$t('Save Project settings')}</Button
						>
					</div>
				</form>
			</Panel>
		{/if}
		{#if can('project.delete')}
			<Panel>
				<Button variant="danger" disabled={busy} onclick={() => (deleteDialogOpen = true)}
					>{$t('Delete Project')}</Button
				>
			</Panel>
		{/if}

		<Panel>
			<h2>{$t('Participation')}</h2>
			{#if project.participation === 'workspace'}
				<p class="text-sm text-surface-600-400">
					{$t('All active Workspace members participate in this Project.')}
				</p>
			{:else}
				<p class="text-sm text-surface-600-400">
					{#if project.participation === 'managed'}
						{$t(
							'Managed Projects are visible only to their participants and Workspace owners/admins.'
						)}
					{:else}
						{$t(
							'Open Projects are visible to all Workspace members. Joining one adds it to Your Projects.'
						)}
					{/if}
				</p>
				{#if project.members.length > 0}
					<ul class="mt-3 grid grid-cols-1 gap-2">
						{#each project.members as member (member.user_id)}<li
								class="flex items-center justify-between gap-2 border-t border-surface-300-700 py-2"
							>
								<span>{member.username}</span>
								{#if can('project_membership.manage')}<Button
										size="sm"
										variant="tonal"
										disabled={busy}
										onclick={() => void removeMember(member.user_id)}>{$t('Remove')}</Button
									>{/if}
							</li>{/each}
					</ul>
				{:else}<p class="mt-3 text-sm text-surface-600-400">
						{$t('No Project participants yet.')}
					</p>{/if}
				{#if can('project_membership.manage')}<form
						class="mt-4 flex flex-wrap gap-2"
						onsubmit={addMember}
					>
						<input
							class="input min-w-64 flex-1"
							bind:value={username}
							placeholder={$t('Exact username')}
							required
						/><Button disabled={busy || !username.trim()}>{$t('Add participant')}</Button>
					</form>{/if}
			{/if}
		</Panel>

		<Panel>
			<h2>{$t('Items')}</h2>
			{#each project.items as item (item.id)}<ItemRow
					class="grid-cols-[minmax(0,1fr)_auto] items-center"
				>
					<a
						class="grid grid-cols-1 gap-1 no-underline"
						href={resolve(workspaceHref(workspaceId, `item/${item.id}`))}
						><strong><RichText html={item.title_html} /></strong><span class="text-surface-600-400"
							>{item.authors ?? ''}</span
						></a
					>{#if can('project_item.manage')}<Button
							disabled={busy || project.state !== 'active'}
							onclick={() =>
								void mutate(
									() =>
										workspace.api.request(
											'DELETE',
											'/workspaces/{workspace_id}/projects/{project_id}/items/{item_id}',
											{ params: { path: { project_id: projectId, item_id: item.id } } }
										),
									$t('Item removed from Project')
								)}>{$t('Remove')}</Button
						>{/if}
				</ItemRow>{:else}<p class="text-surface-600-400">
					{$t('No Items in this Project.')}
				</p>{/each}
		</Panel>

		<Panel>
			<h2>{$t('Discussion')}</h2>
			{#if discussions.isPending}<p>{$t('Loading discussion…')}</p>
			{:else if discussions.isError}<p class="text-error-700-300">
					{$t('Unable to load Project discussion.')}
				</p>
			{:else}{#each discussions.data ?? [] as message (message.id)}
					<article class="grid grid-cols-1 gap-1 border-t border-surface-300-700 py-3">
						<div class="flex items-center justify-between gap-2">
							<strong>{message.author_username}</strong>
							{#if message.mine && isAllowed(message.authorization, 'project_discussion.delete')}<Button
									size="sm"
									variant="tonal"
									disabled={busy}
									onclick={() => void deleteDiscussion(message.id)}>{$t('Delete')}</Button
								>{/if}
							{#if !message.mine && isAllowed(message.authorization, 'project_discussion.delete')}<Button
									size="sm"
									variant="tonal"
									disabled={busy}
									onclick={() => {
										moderationMessageId = message.id;
										moderationDialogOpen = true;
									}}>{$t('Moderate')}</Button
								>{/if}
						</div>
						<p class="whitespace-pre-wrap">{message.body}</p>
						<small class="text-surface-600-400"
							>{new Date(message.created_at).toLocaleString()}</small
						>
					</article>
				{:else}<p class="text-surface-600-400">{$t('No discussion messages yet.')}</p>{/each}{/if}
			{#if can('project_discussion.create')}
				<form class="mt-3 grid grid-cols-1 gap-2" onsubmit={addDiscussion}>
					<textarea
						class="textarea min-h-24"
						bind:value={body}
						required
						maxlength="10000"
						placeholder={$t('Write a message')}></textarea>
					<div><Button disabled={busy || !body.trim()}>{$t('Post')}</Button></div>
				</form>
			{/if}
		</Panel>
	{/if}
	<PromptDialog
		bind:open={deleteDialogOpen}
		title={$t('Permanently delete this Project?')}
		body={$t('Type the Project name to confirm. This cannot be undone.')}
		label={$t('Project name')}
		placeholder={project?.name ?? ''}
		requireMatch={project?.name ?? ''}
		confirmLabel={$t('Delete Project')}
		{busy}
		onConfirm={(value) => void confirmDeleteProject(value)}
	/>
	<PromptDialog
		bind:open={moderationDialogOpen}
		title={$t('Moderate Discussion message')}
		body={$t('Give a reason for removing this message. The action is recorded in the audit log.')}
		label={$t('Moderation reason')}
		confirmLabel={$t('Remove message')}
		{busy}
		onConfirm={(reason) => void moderateDiscussion(reason)}
	/>
</section>
