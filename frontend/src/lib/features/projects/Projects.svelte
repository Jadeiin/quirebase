<script lang="ts">
	import { resolve } from '$app/paths';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { Dialog, Portal } from '@skeletonlabs/skeleton-svelte';
	import { createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { isUnavailableReadError } from '#lib/api/query-state.js';
	import { can } from '#lib/authorization/can.js';
	import { apiErrorMessage } from '#lib/api/errors.js';
	import Badge from '#lib/design/Badge.svelte';
	import Button from '#lib/design/Button.svelte';
	import Pagination from '#lib/design/Pagination.svelte';
	import DialogCloseButton from '#lib/design/DialogCloseButton.svelte';
	import DialogTriggerButton from '#lib/design/DialogTriggerButton.svelte';
	import Icon from '#lib/design/Icon.svelte';
	import Notice from '#lib/design/Notice.svelte';
	import QueryError from '#lib/design/QueryError.svelte';
	import Panel from '#lib/design/Panel.svelte';
	import SectionHeader from '#lib/design/SectionHeader.svelte';
	import { domainLabel } from '#lib/domain-labels.js';
	import { projectListQuery } from '#lib/features/projects/queries.js';
	import { invalidateProject } from '#lib/query/invalidation.js';
	import { t } from '#lib/i18n.js';
	import { numberFormat } from '#lib/format.js';
	import { createUrlDraft } from '#lib/navigation/url-draft.svelte.js';
	import { libraryHref } from '#lib/features/library/filters.js';
	import { getWorkspaceContext } from '#lib/workspaces/context.svelte.js';
	import { workspaceHref } from '#lib/workspaces/href.js';
	import {
		readProjectListState,
		projectListParameters,
		defaultProjectSortDirection,
		type ProjectListState
	} from './list-state';

	const workspace = getWorkspaceContext();
	const workspaceId = workspace.workspaceId;
	const queryClient = useQueryClient();
	const listing = $derived(readProjectListState(page.url.searchParams));
	const id = $props.id();
	const offset = $derived((listing.page - 1) * listing.pageSize);
	function destination(change: Partial<ProjectListState>) {
		const parameters = projectListParameters({ ...listing, ...change });
		const path = workspaceHref(workspaceId, 'projects');
		return resolve(parameters ? `${path}?${parameters}` : path);
	}
	function navigate(change: Partial<ProjectListState>, replace = false) {
		void goto(destination(change), { reset: false, replace });
	}
	const searchDraft = createUrlDraft({
		read: (url) => readProjectListState(url.searchParams).search,
		href: (search) => destination({ search, page: 1 })
	});
	const projects = createQuery(() =>
		projectListQuery(workspaceId, listing.view, offset, listing.search, listing.pageSize, {
			state: listing.state,
			sort: listing.sort,
			direction: listing.direction
		})
	);
	const available = $derived(projects.data != null && !isUnavailableReadError(projects.error));
	const total = $derived(available ? (projects.data?.total ?? 0) : 0);
	const pageCount = $derived(Math.max(1, Math.ceil(total / listing.pageSize)));
	$effect(() => {
		if (
			projects.isSuccess &&
			!projects.isFetching &&
			projects.data != null &&
			offset >= projects.data.total &&
			offset > 0
		)
			navigate({ page: pageCount }, true);
	});
	const nextDirection = $derived(listing.direction === 'asc' ? 'desc' : 'asc');
	function orderLabel(direction: ProjectListState['direction']) {
		if (listing.sort === 'name') return direction === 'asc' ? $t('A–Z') : $t('Z–A');
		return direction === 'asc' ? $t('Oldest first') : $t('Newest first');
	}
	const directionHint = $derived(
		$t('Sort order: {current}. Switch to {next}.', {
			current: orderLabel(listing.direction),
			next: orderLabel(nextDirection)
		})
	);

	let createOpen = $state(false);
	let name = $state('');
	let description = $state('');
	let participation = $state<'workspace' | 'open' | 'managed'>('open');
	const allowedParticipation = $derived(workspace.view?.allowed_project_participations ?? []);
	$effect(() => {
		if (!allowedParticipation.includes(participation) && allowedParticipation[0]) {
			participation = allowedParticipation[0];
		}
	});
	let busy = $state(false);
	let error = $state('');
	let createError = $state('');

	async function refresh() {
		await invalidateProject(queryClient, workspaceId);
	}

	async function createProject() {
		if (busy || !allowedParticipation.includes(participation)) return;
		busy = true;
		createError = '';
		try {
			const created = await workspace.api.request('POST', '/workspaces/{workspace_id}/projects', {
				body: { name: name.trim(), description, participation }
			});
			name = '';
			description = '';
			participation = allowedParticipation.includes('open')
				? 'open'
				: (allowedParticipation[0] ?? 'open');
			createOpen = false;
			await refresh();
			await goto(resolve(workspaceHref(workspaceId, `projects/${created.id}`)));
		} catch (reason) {
			createError = apiErrorMessage(reason, $t('Unable to create Project'));
		} finally {
			busy = false;
		}
	}

	async function changeParticipation(projectId: string, action: 'join' | 'leave') {
		if (busy) return;
		busy = true;
		error = '';
		try {
			if (action === 'join') {
				await workspace.api.request(
					'POST',
					'/workspaces/{workspace_id}/projects/{project_id}/join',
					{
						params: { path: { project_id: projectId } }
					}
				);
			} else {
				await workspace.api.request(
					'POST',
					'/workspaces/{workspace_id}/projects/{project_id}/leave',
					{
						params: { path: { project_id: projectId } }
					}
				);
			}
			await refresh();
		} catch (reason) {
			error = apiErrorMessage(
				reason,
				action === 'join' ? $t('Unable to join Project') : $t('Unable to leave Project')
			);
			// A failed response can follow a committed membership change.
			await refresh();
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
			{$t('Organize Items and collaborate in Projects.')}
		</p>
	</div>
	{#snippet actions()}
		{#if allowedParticipation.length > 0}
			<Dialog
				open={createOpen}
				onOpenChange={(details) => {
					if (busy) return;
					createOpen = details.open;
					if (!details.open) createError = '';
				}}
			>
				<DialogTriggerButton><Icon name="plus" /> {$t('New Project')}</DialogTriggerButton>
				<Portal>
					<Dialog.Backdrop class="fixed inset-0 z-70 bg-surface-950/45 backdrop-blur-[2px]" />
					<Dialog.Positioner class="fixed inset-0 z-71 grid grid-cols-1 place-items-center p-4">
						<Dialog.Content
							class="w-full max-w-lg rounded-container border border-surface-300-700 bg-surface-50-950 p-5 shadow-2xl"
						>
							<SectionHeader>
								<Dialog.Title class="text-xl font-bold">{$t('Create Project')}</Dialog.Title>
								{#snippet actions()}<DialogCloseButton disabled={busy} />{/snippet}
							</SectionHeader>
							{#if createError}<Notice variant="error" class="mb-3">{createError}</Notice>{/if}
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
										disabled={busy}
										required
										maxlength="240"
									/></label
								>
								<label class="grid grid-cols-1 gap-1"
									>{$t('Description')}<textarea
										class="textarea min-h-28"
										bind:value={description}
										disabled={busy}
										maxlength="2000"></textarea></label
								>
								<label class="grid grid-cols-1 gap-1"
									>{$t('Participation')}<select
										class="select"
										bind:value={participation}
										disabled={busy}
									>
										{#each allowedParticipation as value (value)}
											<option {value}>{$t(domainLabel(value))}</option>
										{/each}
									</select></label
								>
								<p class="text-sm text-surface-600-400">
									{#if participation === 'workspace'}
										{$t('All active Workspace members participate in this Project.')}
									{:else if participation === 'open'}
										{$t('Active Workspace members can choose to join or leave this Project.')}
										{$t('You will join automatically when you create an open Project.')}
									{:else}
										{$t(
											'Workspace owners and admins create managed Projects and manage participants.'
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

<Panel class="mb-4">
	<form
		class="flex min-w-0 flex-wrap items-end gap-3"
		onsubmit={(event) => {
			event.preventDefault();
			navigate({ search: searchDraft.value.trim(), page: 1 });
		}}
	>
		<label class="grid min-w-0 grow basis-full grid-cols-1 gap-1 text-sm xl:basis-48">
			{$t('Search Projects')}
			<input
				class="input h-9 field-sm"
				type="search"
				bind:value={searchDraft.value}
				oncompositionstart={() => searchDraft.compositionStart()}
				oncompositionend={() => searchDraft.compositionEnd()}
			/>
		</label>
		<label class="grid min-w-0 grow basis-36 grid-cols-1 gap-1 text-sm xl:grow-0">
			{$t('Projects')}
			<select
				class="select h-9 field-sm"
				value={listing.view}
				onchange={(event) => {
					const value = event.currentTarget.value;
					navigate({ view: value === 'mine' || value === 'joinable' ? value : 'all', page: 1 });
				}}
			>
				<option value="all">{$t('All Projects')}</option>
				<option value="mine">{$t('Your Projects')}</option>
				<option value="joinable">{$t('Open Projects')}</option>
			</select>
		</label>
		<label class="grid min-w-0 grow basis-36 grid-cols-1 gap-1 text-sm xl:grow-0">
			{$t('State')}
			<select
				class="select h-9 field-sm"
				value={listing.state}
				onchange={(event) => {
					const value = event.currentTarget.value;
					navigate({ state: value === 'active' || value === 'archived' ? value : '', page: 1 });
				}}
			>
				<option value="">{$t('Any state')}</option>
				<option value="active">{$t('Active')}</option>
				<option value="archived">{$t('Archived')}</option>
			</select>
		</label>
		<div class="grid min-w-37 grow basis-36 grid-cols-1 gap-1 text-sm xl:grow-0">
			<label for={`${id}-sort`}>{$t('Sort By')}</label>
			<div
				role="group"
				aria-label={$t('Sort')}
				class="field-group min-w-0 grid-cols-[minmax(0,1fr)_auto] gap-0"
			>
				<select
					id={`${id}-sort`}
					class="select h-9 min-w-28 field-sm"
					value={listing.sort}
					onchange={(event) => {
						const value = event.currentTarget.value;
						const sort = value === 'created' || value === 'updated' ? value : 'name';
						navigate({ sort, direction: defaultProjectSortDirection(sort), page: 1 });
					}}
				>
					<option value="name">{$t('Name')}</option>
					<option value="created">{$t('Created')}</option>
					<option value="updated">{$t('Updated')}</option>
				</select>
				<Button
					type="button"
					variant="icon"
					class="-ml-px size-9"
					aria-label={directionHint}
					title={directionHint}
					onclick={() => navigate({ direction: nextDirection, page: 1 })}
				>
					<Icon name={listing.direction === 'asc' ? 'arrow-up' : 'arrow-down'} size={16} />
				</Button>
			</div>
		</div>
	</form>
</Panel>

{#if error}<Notice variant="error" class="mb-4">{error}</Notice>{/if}
{#if projects.isError || (!projects.isPending && !available)}
	<QueryError
		message={$t('Unable to load Projects.')}
		busy={projects.isFetching}
		onRetry={() => void projects.refetch()}
	/>
{/if}

<Panel padding="none" class="min-w-0">
	<SectionHeader class="px-5 pt-5" spacing="compact">
		<h2>
			{$t('Projects')}
			{#if available}<span class="text-base font-normal text-surface-600-400"
					>{$numberFormat.format(total)}</span
				>{/if}
		</h2>
	</SectionHeader>
	{#if available && projects.data}
		{#if projects.data.items.length}
			<ul aria-label={$t('Projects')}>
				{#each projects.data.items as project (project.id)}
					<li
						aria-label={project.name}
						class="flex min-w-0 flex-col gap-4 border-b border-surface-300-700 px-5 py-4 last:border-b-0 sm:flex-row"
					>
						<div class="min-w-0 flex-1">
							<h3 class="text-base">
								<a
									class="line-clamp-2 font-semibold wrap-anywhere hover:text-primary-800-200"
									href={resolve(workspaceHref(workspaceId, `projects/${project.id}`))}
									title={project.name}>{project.name}</a
								>
							</h3>
							{#if project.description}
								<p
									class="mt-1 line-clamp-2 text-sm wrap-anywhere text-surface-600-400"
									title={project.description}
								>
									{project.description}
								</p>
							{/if}
							<div
								class="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-surface-600-400"
							>
								<span
									>{$t('{count, plural, one {# Item} other {# Items}}', {
										count: project.item_count
									})}</span
								>
								<span aria-hidden="true">·</span>
								<span>{$t(domainLabel(project.participation))}</span>
								{#if project.is_participating && project.participation !== 'workspace'}
									<span aria-hidden="true">·</span>
									<span>{$t('Joined')}</span>
								{/if}
								{#if project.state === 'archived'}
									<Badge>{$t(domainLabel(project.state))}</Badge>
								{/if}
							</div>
						</div>
						<div class="flex shrink-0 flex-wrap items-center gap-2 self-start">
							<Button
								as="a"
								size="sm"
								href={resolve(libraryHref(workspaceId, { project: project.id }))}
								>{$t('Open in Library')}</Button
							>
							{#if can(project.authorization, 'project_participation.join')}
								<Button
									size="sm"
									disabled={busy}
									onclick={() => changeParticipation(project.id, 'join')}>{$t('Join')}</Button
								>
							{:else if can(project.authorization, 'project_participation.leave')}
								<Button
									size="sm"
									disabled={busy}
									onclick={() => changeParticipation(project.id, 'leave')}
									>{$t('Leave Project')}</Button
								>
							{/if}
						</div>
					</li>
				{/each}
			</ul>
		{:else}<p class="px-5 pb-5 text-surface-600-400">{$t('No matching Projects.')}</p>{/if}
	{:else if projects.isPending}<p class="px-5 pb-5 text-surface-600-400">
			{$t('Loading Projects…')}
		</p>{/if}
	<Pagination
		page={listing.page}
		{pageCount}
		pageSize={listing.pageSize}
		{total}
		onPageSize={(pageSize) => navigate({ pageSize, page: 1 })}
		onPage={(page) => navigate({ page })}
		busy={projects.isFetching}
		label={$t('Projects')}
	/>
</Panel>
