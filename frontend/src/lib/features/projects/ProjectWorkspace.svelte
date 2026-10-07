<script lang="ts">
	import { Combobox, Portal, useListCollection } from '@skeletonlabs/skeleton-svelte';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { createInfiniteQuery, createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { ApiError } from '#lib/api/client.js';
	import { apiErrorMessage } from '#lib/api/errors.js';
	import { can as isAllowed, type AuthorizationAction } from '#lib/authorization/can.js';
	import type { components } from '#lib/api/schema.js';
	import ConfirmDialog from '#lib/design/ConfirmDialog.svelte';
	import Button from '#lib/design/Button.svelte';
	import ItemRow from '#lib/design/ItemRow.svelte';
	import Notice from '#lib/design/Notice.svelte';
	import Panel from '#lib/design/Panel.svelte';
	import Pagination from '#lib/design/Pagination.svelte';
	import { libraryListQuery } from '#lib/features/library/queries.js';
	import { memberOptionsQuery } from '#lib/workspaces/queries.js';
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
	let itemPage = $state(1);
	let itemSearch = $state('');
	const items = createQuery(() => ({
		...libraryListQuery(
			workspaceId,
			{ query: itemSearch, project: projectId, tag: '', year: '', keyword: '', author: '' },
			itemPage
		),
		enabled: Boolean(project)
	}));
	let activeProjectId = $state('');
	$effect(() => {
		if (activeProjectId !== projectId) {
			activeProjectId = projectId;
			itemPage = 1;
			itemSearch = '';
			memberSearch = '';
			selectedMemberId = '';
			selectedMember = undefined;
		}
	});
	$effect(() => {
		if (!items.isFetching && items.data) {
			const lastPage = Math.max(1, Math.ceil(items.data.total / items.data.limit));
			if (itemPage > lastPage) itemPage = lastPage;
		}
	});
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
	let memberSearch = $state('');
	let selectedMemberId = $state('');
	const directory = createInfiniteQuery(() => ({
		...memberOptionsQuery(workspaceId, memberSearch),
		enabled: can('project_membership.manage')
	}));
	const availableMembers = $derived(
		(directory.data ?? []).filter(
			(member) =>
				!project?.active_participants.some((participant) => participant.user_id === member.user_id)
		)
	);
	let selectedMember = $state<{ user_id: string; username: string } | undefined>();
	const matchingMembers = $derived(
		selectedMember
			? [
					selectedMember,
					...availableMembers.filter((member) => member.user_id !== selectedMember?.user_id)
				]
			: availableMembers
	);
	const collection = $derived(
		useListCollection({
			items: matchingMembers,
			itemToValue: (member) => member.user_id,
			itemToString: (member) => member.username
		})
	);
	let body = $state('');
	let settingsName = $state('');
	let settingsDescription = $state('');
	let settingsParticipation = $state<components['schemas']['ProjectParticipation']>('workspace');
	let participationDialogOpen = $state(false);
	let pendingSettings = $state<
		{ projectId: string; changes: components['schemas']['ProjectSettingsRequest'] } | undefined
	>();
	let deleteDialogOpen = $state(false);
	let moderationMessageId = $state<string | null>(null);
	let moderationDialogOpen = $state(false);

	$effect(() => {
		if (pendingSettings && pendingSettings.projectId !== projectId) {
			participationDialogOpen = false;
			pendingSettings = undefined;
		}
	});

	$effect(() => {
		if (!project) return;
		settingsName = project.name;
		settingsDescription = project.description;
		settingsParticipation = project.participation;
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

	async function applySettings(
		targetProjectId: string,
		changes: components['schemas']['ProjectSettingsRequest']
	) {
		if (
			targetProjectId !== projectId ||
			project?.id !== targetProjectId ||
			!can('project.update') ||
			(changes.participation &&
				!project?.allowed_participation_changes.includes(changes.participation))
		)
			return;
		participationDialogOpen = false;
		pendingSettings = undefined;
		await mutate(
			() =>
				workspace.api.request('PATCH', '/workspaces/{workspace_id}/projects/{project_id}', {
					params: { path: { project_id: targetProjectId } },
					body: changes
				}),
			$t('Project settings saved')
		);
	}

	async function saveSettings(event: SubmitEvent) {
		event.preventDefault();
		if (!project || project.id !== projectId || !can('project.update')) return;
		const changes: components['schemas']['ProjectSettingsRequest'] = {};
		if (settingsName.trim() !== project.name) changes.name = settingsName.trim();
		if (settingsDescription !== project.description) changes.description = settingsDescription;
		if (settingsParticipation !== project.participation) {
			if (!project.allowed_participation_changes.includes(settingsParticipation)) return;
			changes.participation = settingsParticipation;
		}
		if (!Object.keys(changes).length) return;
		if (changes.participation === 'workspace') {
			pendingSettings = { projectId, changes };
			participationDialogOpen = true;
			return;
		}
		await applySettings(projectId, changes);
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
		if (
			busy ||
			!selectedMember ||
			selectedMember.user_id !== selectedMemberId ||
			project?.active_participants.some((member) => member.user_id === selectedMemberId) ||
			!can('project_membership.manage')
		)
			return;
		const username = selectedMember.username;
		const added = await mutate(
			() =>
				workspace.api.request(
					'POST',
					'/workspaces/{workspace_id}/projects/{project_id}/participants',
					{
						params: { path: { project_id: projectId } },
						body: { username }
					}
				),
			$t('Project participant added')
		);
		if (added) {
			selectedMemberId = '';
			selectedMember = undefined;
			memberSearch = '';
		} else await directory.refetch();
	}

	async function removeMember(userId: string) {
		await mutate(
			() =>
				workspace.api.request(
					'DELETE',
					'/workspaces/{workspace_id}/projects/{project_id}/participants/{user_id}',
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
							>{#if project.participation === 'workspace' || project.allowed_participation_changes.includes('workspace')}<option
									value="workspace">{$t(domainLabel('workspace'))}</option
								>{/if}{#if project.participation === 'open' || project.allowed_participation_changes.includes('open')}<option
									value="open">{$t(domainLabel('open'))}</option
								>{/if}{#if project.participation === 'managed' || project.allowed_participation_changes.includes('managed')}<option
									value="managed">{$t(domainLabel('managed'))}</option
								>{/if}</select
						></label
					>
					{#if settingsParticipation !== project.participation}
						<p class="text-sm text-surface-600-400 md:col-span-2">
							{#if settingsParticipation === 'workspace'}
								{$t('All active Workspace members will participate in this Project.')}
							{:else if settingsParticipation === 'managed' && project.participation === 'workspace'}
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
								(settingsParticipation !== project.participation &&
									!project.allowed_participation_changes.includes(settingsParticipation))}
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
				{#if project.active_participants.length > 0}
					<ul class="mt-3 grid grid-cols-1 gap-2">
						{#each project.active_participants as member (member.user_id)}<li
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
				{#if can('project_membership.manage')}
					{#if directory.isPending}<p>{$t('Loading members…')}</p>
					{:else if directory.isError}
						<Notice variant="error">{$t('Unable to load members.')}</Notice>
						<Button onclick={() => void directory.refetch()}>{$t('Retry')}</Button>
					{/if}
					<form class="mt-4 flex flex-wrap items-end gap-2" onsubmit={addMember}>
						<Combobox
							class="min-w-64 flex-1"
							{collection}
							inputValue={selectedMember?.username ?? memberSearch}
							value={selectedMemberId ? [selectedMemberId] : []}
							disabled={busy}
							openOnClick
							onInputValueChange={(details) => {
								if (details.reason === 'input-change') {
									memberSearch = details.inputValue;
									selectedMemberId = '';
									selectedMember = undefined;
								}
							}}
							onValueChange={(details) => {
								selectedMemberId = details.value[0] ?? '';
								selectedMember = matchingMembers.find(
									(member) => member.user_id === selectedMemberId
								);
							}}
						>
							<Combobox.Label>{$t('Workspace member')}</Combobox.Label>
							<Combobox.Control>
								<Combobox.Input placeholder={$t('Search members')} />
								<Combobox.Trigger aria-label={$t('Show members')}>⌄</Combobox.Trigger>
							</Combobox.Control>
							<Portal
								><Combobox.Positioner
									><Combobox.Content>
										{#each matchingMembers as member (member.user_id)}
											<Combobox.Item item={member}
												><Combobox.ItemText>{member.username}</Combobox.ItemText></Combobox.Item
											>
										{:else}<p class="p-3">{$t('No matching members.')}</p>{/each}
									</Combobox.Content></Combobox.Positioner
								></Portal
							>
						</Combobox>
						{#if directory.hasNextPage}<Button
								type="button"
								disabled={directory.isFetchingNextPage}
								onclick={() => void directory.fetchNextPage()}>{$t('Load more members')}</Button
							>{/if}
						<Button disabled={busy || !selectedMember}>{$t('Add participant')}</Button>
					</form>
				{/if}
			{/if}
		</Panel>

		<Panel>
			<h2>{$t('Items')}</h2>
			<input
				class="input"
				aria-label={$t('Search Items')}
				placeholder={$t('Search Items')}
				value={itemSearch}
				oninput={(event) => {
					itemSearch = event.currentTarget.value;
					itemPage = 1;
				}}
			/>
			{#if items.isPending}<p>{$t('Loading Items…')}</p>
			{:else if items.isError}<Notice variant="error">{$t('Unable to load Items.')}</Notice>
			{:else}
				{#each items.data?.items ?? [] as item (item.id)}<ItemRow
						class="grid-cols-[minmax(0,1fr)_auto] items-center"
					>
						<a
							class="grid grid-cols-1 gap-1 no-underline"
							href={resolve(workspaceHref(workspaceId, `item/${item.id}`))}
							><strong><RichText html={item.title_html} /></strong><span
								class="text-surface-600-400">{item.authors ?? ''}</span
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
						{itemSearch ? $t('No matching Items.') : $t('No Items in this Project.')}
					</p>{/each}
			{/if}
			<Pagination
				page={itemPage}
				pageCount={Math.max(1, Math.ceil((items.data?.total ?? 0) / (items.data?.limit ?? 25)))}
				onPage={(page) => (itemPage = page)}
				label={$t('Items pagination')}
				busy={items.isFetching}
			/>
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
	<ConfirmDialog
		bind:open={participationDialogOpen}
		title={$t('Clear Project participant selection?')}
		body={$t(
			'All active Workspace members will participate. Existing participant selections will be permanently cleared, including suspended members. Switching back will not restore them.'
		)}
		confirmLabel={$t('Clear selection and save')}
		{busy}
		onConfirm={() => {
			if (pendingSettings) void applySettings(pendingSettings.projectId, pendingSettings.changes);
		}}
	/>
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
