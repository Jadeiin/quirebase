<script lang="ts">
	import { Combobox, Dialog, Portal, useListCollection } from '@skeletonlabs/skeleton-svelte';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import {
		readProjectItemListState,
		projectItemListParameters,
		type ProjectItemListState
	} from './list-state';
	import { createInfiniteQuery, createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { ApiError } from '#lib/api/client.js';
	import { apiErrorMessage } from '#lib/api/errors.js';
	import { can as isAllowed, type AuthorizationAction } from '#lib/authorization/can.js';
	import type { components } from '#lib/api/schema.js';
	import ConfirmDialog from '#lib/design/ConfirmDialog.svelte';
	import DialogCloseButton from '#lib/design/DialogCloseButton.svelte';
	import Button from '#lib/design/Button.svelte';
	import Icon from '#lib/design/Icon.svelte';
	import AuthorLine from '#lib/design/AuthorLine.svelte';
	import BibliographicSummary from '#lib/design/BibliographicSummary.svelte';
	import Notice from '#lib/design/Notice.svelte';
	import QueryError from '#lib/design/QueryError.svelte';
	import Panel from '#lib/design/Panel.svelte';
	import Pagination from '#lib/design/Pagination.svelte';
	import { libraryListQuery } from '#lib/features/library/queries.js';
	import { libraryHref } from '#lib/features/library/filters.js';
	import { libraryItemHref, libraryReturnTo } from '#lib/features/library/return-context.js';
	import { memberOptionsQuery } from '#lib/workspaces/queries.js';
	import PromptDialog from '#lib/design/PromptDialog.svelte';
	import RichText from '#lib/design/RichText.svelte';
	import SectionHeader from '#lib/design/SectionHeader.svelte';
	import { domainLabel } from '#lib/domain-labels.js';
	import { projectDetailQuery } from '#lib/features/projects/queries.js';
	import { ph, t } from 'lingui-for-svelte/macro';
	import { toaster } from '#lib/toaster.js';
	import { invalidateProject } from '#lib/query/invalidation.js';
	import { getWorkspaceContext } from '#lib/workspaces/context.svelte.js';
	import { workspaceHref } from '#lib/workspaces/href.js';
	import { workspaceKeys } from '#lib/workspaces/keys.js';

	let { projectId }: { projectId: string } = $props();
	const workspace = getWorkspaceContext();
	const workspaceId = workspace.workspaceId;
	const queryClient = useQueryClient();
	const detail = createQuery(() => projectDetailQuery(workspaceId, projectId));
	const project = $derived(detail.data);
	const listing = $derived(readProjectItemListState(page.url.searchParams));
	const itemPage = $derived(listing.page);
	const itemPageSize = $derived(listing.pageSize);
	const itemSort = $derived(listing.sort);
	const itemSearch = $derived(listing.search);
	const libraryDestination = $derived(
		libraryHref(
			workspaceId,
			{ query: itemSearch, project: projectId, sort: itemSort },
			itemPage,
			itemPageSize
		)
	);
	function navigateItems(change: Partial<ProjectItemListState>, replace = false) {
		const parameters = projectItemListParameters({ ...listing, ...change });
		const path = workspaceHref(workspaceId, `projects/${projectId}`);
		void goto(resolve(parameters ? `${path}?${parameters}` : path), {
			reset: false,
			replace
		});
	}
	const items = createQuery(() => ({
		...libraryListQuery(
			workspaceId,
			{ query: itemSearch, project: projectId, sort: itemSort },
			itemPage,
			itemPageSize
		),
		enabled: Boolean(project)
	}));
	let activeProjectId = $state('');
	$effect(() => {
		if (activeProjectId !== projectId) {
			activeProjectId = projectId;
			memberSearch = '';
			selectedMemberId = '';
			selectedMember = undefined;
			settingsDialogOpen = false;
			deleteDialogOpen = false;
			removeItemDialogOpen = false;
			pendingRemoveItem = undefined;
			moderationDialogOpen = false;
			moderationMessageId = '';
		}
	});
	$effect(() => {
		if (!items.isFetching && items.data) {
			const lastPage = Math.max(1, Math.ceil(items.data.total / items.data.limit));
			if (itemPage > lastPage) navigateItems({ page: lastPage }, true);
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
		enabled: can('project_participation.manage')
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
	let settingsDialogOpen = $state(false);
	let settingsName = $state('');
	let settingsDescription = $state('');
	let settingsParticipation = $state<components['schemas']['ProjectParticipation']>('workspace');
	let settingsBaseline =
		$state<
			Pick<
				components['schemas']['ProjectDetailView'],
				'id' | 'name' | 'description' | 'participation'
			>
		>();
	let participationDialogOpen = $state(false);
	let pendingSettings = $state<
		{ projectId: string; changes: components['schemas']['ProjectSettingsRequest'] } | undefined
	>();
	let deleteDialogOpen = $state(false);
	let removeItemDialogOpen = $state(false);
	let pendingRemoveItem = $state<{ projectId: string; itemId: string }>();
	let moderationMessageId = $state<string | null>(null);
	let moderationDialogOpen = $state(false);

	$effect(() => {
		if (pendingSettings && pendingSettings.projectId !== projectId) {
			participationDialogOpen = false;
			pendingSettings = undefined;
		}
	});

	$effect(() => {
		if (!can('project.update')) settingsDialogOpen = false;
	});

	$effect(() => {
		const previous = settingsBaseline;
		if (!settingsDialogOpen || !project || previous?.id !== project.id) return;
		if (
			previous.name === project.name &&
			previous.description === project.description &&
			previous.participation === project.participation
		)
			return;
		// Refresh untouched fields while keeping the user's edits across failed saves.
		if (settingsName.trim() === previous.name) settingsName = project.name;
		if (settingsDescription === previous.description) settingsDescription = project.description;
		if (settingsParticipation === previous.participation)
			settingsParticipation = project.participation;
		settingsBaseline = {
			id: project.id,
			name: project.name,
			description: project.description,
			participation: project.participation
		};
	});

	function openSettings() {
		if (!project || !can('project.update')) return;
		participationDialogOpen = false;
		pendingSettings = undefined;
		settingsName = project.name;
		settingsDescription = project.description;
		settingsParticipation = project.participation;
		settingsBaseline = {
			id: project.id,
			name: project.name,
			description: project.description,
			participation: project.participation
		};
		error = '';
		settingsDialogOpen = true;
	}

	async function mutate(
		action: () => Promise<unknown>,
		success: string | undefined,
		reload = true,
		successToast = false
	): Promise<boolean> {
		if (busy) return false;
		busy = true;
		error = '';
		notice = '';
		try {
			await action();
			if (successToast && success) toaster.success({ title: success });
			else if (success) notice = success;
			if (reload) {
				await invalidateProject(queryClient, workspaceId);
			}
			return true;
		} catch (reason) {
			error = apiErrorMessage(reason, $t`Project action failed`);
			if (
				reason instanceof ApiError &&
				['project_lifecycle_error', 'project_participation_conflict'].includes(reason.code)
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
		const saved = await mutate(
			() =>
				workspace.api.request('PATCH', '/workspaces/{workspace_id}/projects/{project_id}', {
					params: { path: { project_id: targetProjectId } },
					body: changes
				}),
			$t`Project settings saved`
		);
		if (saved) settingsDialogOpen = false;
	}

	async function saveSettings(event: SubmitEvent) {
		event.preventDefault();
		if (
			busy ||
			!project ||
			project.id !== projectId ||
			settingsBaseline?.id !== projectId ||
			!can('project.update')
		)
			return;
		const changes: components['schemas']['ProjectSettingsRequest'] = {};
		if (settingsName.trim() !== settingsBaseline.name) changes.name = settingsName.trim();
		if (settingsDescription !== settingsBaseline.description)
			changes.description = settingsDescription;
		if (settingsParticipation !== settingsBaseline.participation) {
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
			$t`Joined Project`
		);
	}

	async function leaveProject() {
		await mutate(
			() =>
				workspace.api.request('POST', '/workspaces/{workspace_id}/projects/{project_id}/leave', {
					params: { path: { project_id: projectId } }
				}),
			$t`Left Project`
		);
	}

	async function addParticipant(event: SubmitEvent) {
		event.preventDefault();
		if (
			busy ||
			!selectedMember ||
			selectedMember.user_id !== selectedMemberId ||
			project?.active_participants.some(
				(participant) => participant.user_id === selectedMemberId
			) ||
			!can('project_participation.manage')
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
			$t`Project participant added`
		);
		if (added) {
			selectedMemberId = '';
			selectedMember = undefined;
			memberSearch = '';
		} else await directory.refetch();
	}

	async function removeParticipant(userId: string) {
		await mutate(
			() =>
				workspace.api.request(
					'DELETE',
					'/workspaces/{workspace_id}/projects/{project_id}/participants/{user_id}',
					{ params: { path: { project_id: projectId, user_id: userId } } }
				),
			$t`Project participant removed`
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
			action === 'archive' ? $t`Project archived` : $t`Project restored`
		);
	}

	async function confirmDeleteProject() {
		const targetProjectId = projectId;
		const targetProjectName = project?.name ?? '';
		const requestedPath = page.url.pathname;
		const deleted = await mutate(
			() =>
				workspace.api.request('DELETE', '/workspaces/{workspace_id}/projects/{project_id}', {
					params: { path: { project_id: targetProjectId } }
				}),
			undefined,
			false
		);
		if (deleted) {
			deleteDialogOpen = false;
			// Deletion removes the Project from every cached directory and
			// selector, including reader annotation sources.
			await invalidateProject(queryClient, workspaceId);
			if (page.url.pathname === requestedPath) {
				await goto(resolve(workspaceHref(workspaceId, 'projects')));
			}
			toaster.success({ title: `${$t`Project deleted`}: ${targetProjectName}` });
		}
	}

	async function confirmRemoveItem() {
		const target = pendingRemoveItem;
		if (
			!target ||
			busy ||
			target.projectId !== projectId ||
			!can('project_item.manage') ||
			project?.state !== 'active'
		)
			return;
		const removed = await mutate(
			() =>
				workspace.api.request(
					'DELETE',
					'/workspaces/{workspace_id}/projects/{project_id}/items/{item_id}',
					{
						params: { path: { project_id: target.projectId, item_id: target.itemId } }
					}
				),
			$t`Item removed from Project`
		);
		if (removed) {
			removeItemDialogOpen = false;
			pendingRemoveItem = undefined;
		}
	}

	async function addDiscussion(event: SubmitEvent) {
		event.preventDefault();
		if (!body.trim()) return;
		const submittedBody = body;
		const posted = await mutate(
			() =>
				workspace.api.request(
					'POST',
					'/workspaces/{workspace_id}/projects/{project_id}/discussions',
					{ params: { path: { project_id: projectId } }, body: { body: submittedBody.trim() } }
				),
			$t`Discussion posted`,
			true,
			true
		);
		if (posted && body === submittedBody) body = '';
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
			$t`Discussion message deleted`
		);
	}

	async function moderateDiscussion(reason: string) {
		const messageId = moderationMessageId;
		if (
			busy ||
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
		const targetProjectId = projectId;
		const moderated = await mutate(
			() =>
				workspace.api.request(
					'POST',
					'/workspaces/{workspace_id}/projects/{project_id}/discussions/{message_id}/moderation',
					{
						params: { path: { project_id: targetProjectId, message_id: messageId } },
						body: { reason: reason.trim() }
					}
				),
			$t`Discussion message moderated`
		);
		if (moderated && projectId === targetProjectId && moderationMessageId === messageId)
			moderationDialogOpen = false;
	}
</script>

<section class="grid grid-cols-1 gap-6">
	<div class="flex flex-wrap items-center justify-between gap-3">
		<a
			class="text-sm text-primary-700-300 no-underline"
			href={resolve(workspaceHref(workspaceId, 'projects'))}>← {$t`Projects`}</a
		>
		{#if project}
			<div class="ml-auto flex flex-wrap justify-end gap-2">
				{#if can('project.update')}
					<Button variant="tonal" size="sm" disabled={busy} onclick={openSettings}>
						<Icon name="settings" size={16} />{$t`Project settings`}
					</Button>
				{/if}
				{#if can('project.delete')}
					<Button
						variant="danger"
						size="sm"
						disabled={busy}
						onclick={() => {
							error = '';
							deleteDialogOpen = true;
						}}>{$t`Delete Project`}</Button
					>
				{/if}
			</div>
		{/if}
	</div>
	{#if error && !settingsDialogOpen && !deleteDialogOpen && !removeItemDialogOpen && !moderationDialogOpen}<Notice
			variant="error">{error}</Notice
		>{/if}
	{#if notice}<Notice>{notice}</Notice>{/if}
	{#if detail.isPending}<p>{$t`Loading Project…`}</p>
	{:else if detail.isError || !project}<QueryError
			message={$t`Unable to load Project.`}
			busy={detail.isFetching}
			onRetry={() => void detail.refetch()}
		/>
	{:else}
		<SectionHeader class="flex-col items-stretch sm:flex-row sm:items-start">
			<div>
				<p class="mb-1 text-sm text-primary-700-300">
					{$t(domainLabel(project.state))} · {$t(domainLabel(project.participation))} · {project.item_count}
					{$t`Items`}
				</p>
				<h1 class="wrap-anywhere">{project.name}</h1>
				<p class="wrap-anywhere text-surface-600-400">
					{project.description || $t`No description`}
				</p>
			</div>
			{#snippet actions()}
				<div class="flex flex-wrap gap-2">
					{#if can('project_participation.join')}<Button
							disabled={busy}
							onclick={() => void joinProject()}>{$t`Join Project`}</Button
						>{/if}
					{#if can('project_participation.leave')}<Button
							variant="tonal"
							disabled={busy}
							onclick={() => void leaveProject()}>{$t`Leave Project`}</Button
						>{/if}
					<Button as="a" href={resolve(libraryDestination)}>{$t`Open in Library`}</Button>
					{#if can('project.archive')}<Button
							variant="tonal"
							disabled={busy}
							onclick={() => void changeState('archive')}>{$t`Archive`}</Button
						>{:else if can('project.restore')}<Button
							disabled={busy}
							onclick={() => void changeState('restore')}>{$t`Restore`}</Button
						>{/if}
				</div>
			{/snippet}
		</SectionHeader>

		<Panel>
			<h2>{$t`Participation`}</h2>
			{#if project.participation === 'workspace'}
				<p class="text-sm text-surface-600-400">
					{$t`All active Workspace members participate in this Project.`}
				</p>
			{:else}
				<p class="text-sm text-surface-600-400">
					{#if project.participation === 'managed'}
						{$t`Managed Projects are visible only to their participants and Workspace owners/admins.`}
					{:else}
						{$t`Open Projects are visible to all Workspace members. Joining one adds it to Your Projects.`}
					{/if}
				</p>
				{#if project.active_participants.length > 0}
					<ul class="mt-3 grid grid-cols-1 gap-2">
						{#each project.active_participants as participant (participant.user_id)}<li
								class="flex items-center justify-between gap-2 border-t border-surface-300-700 py-2"
							>
								<span>{participant.username}</span>
								{#if can('project_participation.manage')}<Button
										size="sm"
										variant="tonal"
										disabled={busy}
										onclick={() => void removeParticipant(participant.user_id)}>{$t`Remove`}</Button
									>{/if}
							</li>{/each}
					</ul>
				{:else}<p class="mt-3 text-sm text-surface-600-400">
						{$t`No Project participants yet.`}
					</p>{/if}
				{#if can('project_participation.manage')}
					{#if directory.isPending}<p>{$t`Loading members…`}</p>
					{:else if directory.isError}
						<Notice variant="error">{$t`Unable to load members.`}</Notice>
						<Button onclick={() => void directory.refetch()}>{$t`Retry`}</Button>
					{/if}
					<form class="mt-4 flex flex-wrap items-end gap-2" onsubmit={addParticipant}>
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
							<Combobox.Label>{$t`Workspace member`}</Combobox.Label>
							<Combobox.Control>
								<Combobox.Input placeholder={$t`Search members`} />
								<Combobox.Trigger aria-label={$t`Show members`}>⌄</Combobox.Trigger>
							</Combobox.Control>
							<Portal
								><Combobox.Positioner
									><Combobox.Content>
										{#each matchingMembers as member (member.user_id)}
											<Combobox.Item item={member}
												><Combobox.ItemText>{member.username}</Combobox.ItemText></Combobox.Item
											>
										{:else}<p class="p-3">{$t`No matching members.`}</p>{/each}
									</Combobox.Content></Combobox.Positioner
								></Portal
							>
						</Combobox>
						{#if directory.hasNextPage}<Button
								type="button"
								disabled={directory.isFetchingNextPage}
								onclick={() => void directory.fetchNextPage()}>{$t`Load more members`}</Button
							>{/if}
						<Button disabled={busy || !selectedMember}>{$t`Add participant`}</Button>
					</form>
				{/if}
			{/if}
		</Panel>

		<Panel padding="none" aria-labelledby="project-items-title">
			<div class="p-4">
				<h2 id="project-items-title">{$t`Items`}</h2>
				<input
					class="input"
					aria-label={$t`Search Items`}
					placeholder={$t`Search Items`}
					value={itemSearch}
					oninput={(event) => {
						navigateItems({ search: event.currentTarget.value, page: 1 }, true);
					}}
				/>
			</div>
			{#if items.isPending || (!items.data && items.isFetching)}<p class="px-4 pb-4">
					{$t`Loading Items…`}
				</p>
			{:else if items.isError || !items.data}<div class="px-4 pb-4">
					<QueryError
						message={$t`Unable to load Items.`}
						busy={items.isFetching}
						onRetry={() => void items.refetch()}
					/>
				</div>
			{:else}
				<div class="divide-y divide-surface-300-700">
					{#each items.data?.items ?? [] as item (item.id)}<article
							class="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-start gap-3 px-4 py-4"
						>
							<a
								class="min-w-0 no-underline hover:text-primary-700-300"
								aria-labelledby={`project-item-title-${item.id}`}
								href={resolve(
									libraryItemHref(
										workspaceId,
										item.id,
										'',
										libraryReturnTo(workspaceId, libraryDestination, item.id)
									)
								)}
								><BibliographicSummary>
									{#snippet title()}<span id={`project-item-title-${item.id}`}
											><RichText html={item.title_html} /></span
										>{/snippet}
									{#snippet authors()}
										{#if item.authors.length}<AuthorLine
												names={item.authors.map((author) => author.full_name)}
											/>{:else}{$t`Unknown authors`}{/if}
									{/snippet}
									{item.publication_title || '—'} · {item.publication_date || '—'}
								</BibliographicSummary></a
							>{#if can('project_item.manage')}<Button
									size="sm"
									disabled={busy || project.state !== 'active'}
									onclick={() => {
										error = '';
										pendingRemoveItem = { projectId, itemId: item.id };
										removeItemDialogOpen = true;
									}}>{$t`Remove`}</Button
								>{/if}
						</article>{:else}<p class="px-4 pb-4 text-surface-600-400">
							{itemSearch ? $t`No matching Items.` : $t`No Items in this Project.`}
						</p>{/each}
				</div>
			{/if}
			<Pagination
				page={itemPage}
				pageCount={Math.max(1, Math.ceil((items.data?.total ?? 0) / itemPageSize))}
				pageSize={itemPageSize}
				total={items.data?.total ?? 0}
				onPageSize={(size) => {
					navigateItems({ pageSize: size, page: 1 });
				}}
				sort={itemSort}
				sortOptions={[
					{ value: 'updated', label: $t`Recently updated` },
					{ value: 'created', label: $t`Recently added` },
					{ value: 'title', label: $t`Title` }
				]}
				onSort={(value) => {
					navigateItems({
						sort: value === 'title' || value === 'created' ? value : 'updated',
						page: 1
					});
				}}
				onPage={(page) => navigateItems({ page })}
				label={$t`Items pagination`}
				busy={items.isFetching}
			/>
		</Panel>

		<Panel>
			<h2>{$t`Discussion`}</h2>
			{#if discussions.isPending}<p>{$t`Loading discussion…`}</p>
			{:else if discussions.isError}<QueryError
					message={$t`Unable to load Project discussion.`}
					busy={discussions.isFetching}
					onRetry={() => void discussions.refetch()}
				/>
			{:else}{#each discussions.data ?? [] as message (message.id)}
					<article class="grid grid-cols-1 gap-1 border-t border-surface-300-700 py-3">
						<div class="flex items-center justify-between gap-2">
							<strong>{message.author_username}</strong>
							{#if message.mine && isAllowed(message.authorization, 'project_discussion.delete')}<Button
									size="sm"
									variant="tonal"
									disabled={busy}
									onclick={() => void deleteDiscussion(message.id)}>{$t`Delete`}</Button
								>{/if}
							{#if !message.mine && isAllowed(message.authorization, 'project_discussion.delete')}<Button
									size="sm"
									variant="tonal"
									disabled={busy}
									onclick={() => {
										moderationMessageId = message.id;
										moderationDialogOpen = true;
									}}>{$t`Moderate`}</Button
								>{/if}
						</div>
						<p class="whitespace-pre-wrap">{message.body}</p>
						<small class="text-surface-600-400"
							>{new Date(message.created_at).toLocaleString()}</small
						>
					</article>
				{:else}<p class="text-surface-600-400">{$t`No discussion messages yet.`}</p>{/each}{/if}
			{#if can('project_discussion.create')}
				<form class="mt-3 grid grid-cols-1 gap-2" onsubmit={addDiscussion}>
					<textarea
						class="textarea min-h-24"
						bind:value={body}
						required
						maxlength="10000"
						placeholder={$t`Write a message`}></textarea>
					<div><Button disabled={busy || !body.trim()}>{$t`Post`}</Button></div>
				</form>
			{/if}
		</Panel>
	{/if}
	{#if project && can('project.update')}
		<Dialog
			open={settingsDialogOpen}
			onOpenChange={(details) => {
				if (busy) return;
				settingsDialogOpen = details.open;
				if (!details.open) {
					participationDialogOpen = false;
					pendingSettings = undefined;
				}
			}}
		>
			<Portal>
				<Dialog.Backdrop class="fixed inset-0 z-70 bg-surface-950/45 backdrop-blur-[2px]" />
				<Dialog.Positioner class="fixed inset-0 z-71 grid grid-cols-1 place-items-center p-4">
					<Dialog.Content
						class="max-h-[calc(100dvh-2rem)] w-full max-w-xl overflow-y-auto rounded-container border border-surface-300-700 bg-surface-50-950 p-5 shadow-2xl"
					>
						<SectionHeader>
							<Dialog.Title class="text-lg font-bold"
								>{participationDialogOpen
									? $t`Clear Project participant selection?`
									: $t`Project settings`}</Dialog.Title
							>
							{#snippet actions()}
								<DialogCloseButton disabled={busy} />
							{/snippet}
						</SectionHeader>
						{#if error}<Notice variant="error" class="mb-4">{error}</Notice>{/if}
						{#if participationDialogOpen}
							<p class="text-sm text-surface-600-400">
								{$t`All active Workspace members will participate. Existing participant selections will be permanently cleared, including suspended members. Switching back will not restore them.`}
							</p>
							<div class="mt-5 flex flex-wrap justify-end gap-2">
								<Button
									variant="tonal"
									disabled={busy}
									onclick={() => {
										participationDialogOpen = false;
										pendingSettings = undefined;
									}}>{$t`Cancel`}</Button
								>
								<Button
									variant="danger-filled"
									disabled={busy}
									onclick={() => {
										if (pendingSettings)
											void applySettings(pendingSettings.projectId, pendingSettings.changes);
									}}>{$t`Clear selection and save`}</Button
								>
							</div>
						{:else}
							<form class="grid grid-cols-1 gap-3 sm:grid-cols-2" onsubmit={saveSettings}>
								<label class="grid grid-cols-1 gap-1"
									>{$t`Name`}<input
										class="input"
										bind:value={settingsName}
										disabled={busy}
										required
										maxlength="240"
									/></label
								>
								<label class="grid grid-cols-1 gap-1"
									>{$t`Participation`}<select
										class="select"
										bind:value={settingsParticipation}
										disabled={busy}
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
									<p class="text-sm text-surface-600-400 sm:col-span-2">
										{#if settingsParticipation === 'workspace'}
											{$t`All active Workspace members will participate in this Project.`}
										{:else if settingsParticipation === 'managed' && project.participation === 'workspace'}
											{$t`A managed Project starts with no participants; Workspace owners/admins can add them.`}
										{:else if project.participation === 'workspace'}
											{$t`Switching from Workspace-wide participation starts with you as the first participant.`}
										{:else}
											{$t`Switching between open and managed participation preserves current participants.`}
										{/if}
									</p>
								{/if}
								<label class="grid grid-cols-1 gap-1 sm:col-span-2"
									>{$t`Description`}<textarea
										class="textarea min-h-24"
										disabled={busy}
										bind:value={settingsDescription}></textarea></label
								>
								<div class="flex flex-wrap justify-end gap-2 sm:col-span-2">
									<Button
										type="button"
										variant="tonal"
										disabled={busy}
										onclick={() => (settingsDialogOpen = false)}>{$t`Cancel`}</Button
									>
									<Button
										disabled={busy ||
											!settingsName.trim() ||
											(settingsParticipation !== project.participation &&
												!project.allowed_participation_changes.includes(settingsParticipation))}
										>{$t`Save Project settings`}</Button
									>
								</div>
							</form>
						{/if}
					</Dialog.Content>
				</Dialog.Positioner>
			</Portal>
		</Dialog>
	{/if}

	<ConfirmDialog
		bind:open={removeItemDialogOpen}
		title={$t`Remove Item from Project?`}
		body={$t`Removing this Item from ${ph({ name: project?.name ?? '' })} permanently deletes all of its Project Annotations and Replies in this Project. This cannot be undone. The Item, its files, private Annotations and other Projects are preserved.` +
			(removeItemDialogOpen && error ? ` ${error}` : '')}
		confirmLabel={$t`Remove from Project`}
		{busy}
		onConfirm={() => void confirmRemoveItem()}
	/>
	<PromptDialog
		bind:open={deleteDialogOpen}
		title={$t`Permanently delete this Project?`}
		body={$t`Type the Project name to confirm. This cannot be undone.`}
		label={$t`Project name`}
		placeholder={project?.name ?? ''}
		requireMatch={project?.name ?? ''}
		confirmLabel={$t`Delete Project`}
		{busy}
		error={deleteDialogOpen ? error : ''}
		onConfirm={() => void confirmDeleteProject()}
	/>
	<PromptDialog
		bind:open={moderationDialogOpen}
		title={$t`Moderate Discussion message`}
		error={moderationDialogOpen ? error : ''}
		body={$t`Give a reason for removing this message. The action is recorded in the audit log.`}
		label={$t`Moderation reason`}
		confirmLabel={$t`Remove message`}
		{busy}
		onConfirm={(reason) => void moderateDiscussion(reason)}
	/>
</section>
