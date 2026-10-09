<script lang="ts">
	import { resolve } from '$app/paths';
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { apiRequest } from '#lib/api/client.js';
	import { apiErrorMessage } from '#lib/api/errors.js';
	import Button from '#lib/design/Button.svelte';
	import Pagination from '#lib/design/Pagination.svelte';
	import Notice from '#lib/design/Notice.svelte';
	import { t } from '#lib/i18n.js';
	import { getSession } from '#lib/session.js';
	import { workspaceKeys } from '#lib/workspaces/keys.js';
	import { workspaceHref } from '#lib/workspaces/href.js';
	import {
		defaultWorkspacePreference,
		setDefaultWorkspacePreference
	} from '#lib/workspaces/preference.js';
	import {
		workspaceCreationAvailabilityQuery,
		workspaceListQuery
	} from '#lib/workspaces/queries.js';
	import { domainLabel } from '#lib/domain-labels.js';

	let offset = $state(0);
	let search = $state('');
	const workspaces = createQuery(() => workspaceListQuery(offset, search));
	const pageCount = $derived(Math.max(1, Math.ceil((workspaces.data?.total ?? 0) / 25)));
	$effect(() => {
		if (workspaces.data && offset >= workspaces.data.total && offset > 0)
			offset = (pageCount - 1) * 25;
	});
	const creation = createQuery(() => workspaceCreationAvailabilityQuery());
	const queryClient = useQueryClient();
	const session = getSession().query;
	let name = $state('');
	let ownerUsername = $state('');
	let error = $state('');
	let message = $state('');
	let busy = $state(false);
	let defaultWorkspaceId = $state<string | null>(null);

	onMount(() => {
		defaultWorkspaceId = defaultWorkspacePreference();
	});

	async function createWorkspace() {
		const needsOwnerUsername = creation.data?.owner_username_required ?? false;
		if (!name.trim() || (needsOwnerUsername && !ownerUsername.trim()) || busy) return;
		busy = true;
		error = '';
		message = '';
		try {
			const requestedOwner = ownerUsername.trim();
			const created = await apiRequest('POST', '/workspaces', {
				body: {
					name: name.trim(),
					...(needsOwnerUsername ? { owner_username: requestedOwner } : {})
				}
			});
			await queryClient.invalidateQueries({
				queryKey: workspaceKeys.list(),
				refetchType: 'all'
			});
			const createdForCurrentUser =
				!needsOwnerUsername || requestedOwner === session.data?.user?.username;
			if (createdForCurrentUser) {
				setDefaultWorkspacePreference(created.id);
				await goto(resolve(workspaceHref(created.id)), { replace: true });
			} else {
				name = '';
				ownerUsername = '';
				message = $t(
					'Workspace created. Its owner can open it; you have no content access unless you are also a member.'
				);
			}
		} catch (reason) {
			error = apiErrorMessage(reason, 'Unable to create workspace');
		} finally {
			busy = false;
		}
	}
</script>

<svelte:head><title>{$t('Workspaces · Quirebase')}</title></svelte:head>
<section class="mx-auto grid w-full max-w-5xl grid-cols-1 gap-8">
	<header class="grid grid-cols-1 gap-2">
		<p class="text-sm font-semibold text-primary-700-300">{$t('Workspace')}</p>
		<h1 class="text-3xl font-bold">{$t('Choose a workspace')}</h1>
		<p class="max-w-2xl text-surface-600-400">
			{$t(
				'Each workspace follows the same access and governance rules. Choose one to open its library and projects.'
			)}
		</p>
	</header>

	{#if error}<Notice variant="error">{error}</Notice>{/if}
	{#if message}<Notice>{message}</Notice>{/if}

	<section class="grid grid-cols-1 gap-3" aria-labelledby="available-workspaces-heading">
		<div class="flex flex-wrap items-end justify-between gap-2">
			<div>
				<h2 id="available-workspaces-heading" class="text-xl font-semibold">
					{$t('Your workspaces')}
				</h2>
				<p class="text-sm text-surface-600-400">
					{$t('Your workspace URL determines which data and permissions are in use.')}
				</p>
			</div>
		</div>

		<label
			>{$t('Search workspaces')}<input
				class="input"
				value={search}
				oninput={(event) => {
					search = event.currentTarget.value;
					offset = 0;
				}}
			/></label
		>
		{#if workspaces.isPending}<p class="text-surface-600-400">{$t('Loading workspaces…')}</p>
		{:else if workspaces.isError}<Notice variant="error">{$t('Unable to load workspaces.')}</Notice>
		{:else if workspaces.data?.items.length}
			<div class="grid grid-cols-1 gap-3 md:grid-cols-2">
				{#each workspaces.data.items as workspace (workspace.id)}
					<a
						class="group hover:border-primary-500-400 flex min-h-28 items-center justify-between gap-4 rounded-container border border-surface-300-700 bg-surface-50-950 p-5 text-inherit no-underline transition-colors hover:bg-primary-50-950 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-500"
						href={resolve(workspaceHref(workspace.id))}
						aria-label={$t('Open workspace {name}', { name: workspace.name })}
						onclick={() => {
							setDefaultWorkspacePreference(workspace.id);
							defaultWorkspaceId = workspace.id;
						}}
					>
						<span class="grid min-w-0 grid-cols-1 gap-2">
							<strong class="truncate text-lg">{workspace.name}</strong>
							<span class="flex flex-wrap items-center gap-2 text-sm text-surface-600-400">
								<span>{$t(domainLabel(workspace.current_role))}</span><span aria-hidden="true"
									>·</span
								>
								<span>{$t(domainLabel(workspace.state))}</span>
							</span>
						</span>
						<span
							class="grid shrink-0 grid-cols-1 justify-items-end gap-2 text-sm font-semibold text-primary-700-300"
						>
							{#if workspace.id === defaultWorkspaceId}<span
									class="rounded-full bg-primary-100-900 px-2.5 py-1 text-xs">{$t('Default')}</span
								>{/if}
							<span class="group-hover:underline">{$t('Open Workspace')} →</span>
						</span>
					</a>
				{/each}
			</div>
		{:else}
			<Notice>{$t('No workspaces are available for this account yet.')}</Notice>
		{/if}
		<Pagination
			page={Math.floor(offset / 25) + 1}
			{pageCount}
			onPage={(page) => {
				offset = (page - 1) * 25;
			}}
			busy={workspaces.isFetching}
			label={$t('Workspaces')}
		/>
	</section>

	{#if creation.isPending}<p class="text-sm text-surface-600-400">
			{$t('Checking workspace creation availability…')}
		</p>
	{:else if creation.isError}<Notice variant="error">
			{$t('Unable to check whether you can create a workspace. Refresh and try again.')}
		</Notice>
	{:else if creation.data?.allowed}
		<section
			class="grid max-w-2xl grid-cols-1 gap-4 rounded-container border border-surface-300-700 bg-surface-50-950 p-5"
			aria-labelledby="create-workspace-heading"
		>
			<div class="grid grid-cols-1 gap-1">
				<h2 id="create-workspace-heading" class="text-xl font-semibold">
					{$t('Create a workspace')}
				</h2>
				<p class="text-sm text-surface-600-400">
					{#if creation.data.owner_username_required}
						{$t(
							'Choose an active user to own this workspace. Instance administrators do not automatically get content access.'
						)}
					{:else}
						{$t('You will become its owner and can invite other members later.')}
					{/if}
				</p>
			</div>
			<form
				class="grid grid-cols-1 gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end"
				onsubmit={(event) => {
					event.preventDefault();
					void createWorkspace();
				}}
			>
				<label class="grid grid-cols-1 gap-1"
					>{$t('Workspace name')}<input
						class="input"
						bind:value={name}
						required
						minlength="1"
						maxlength="240"
						autocomplete="organization"
					/></label
				>
				{#if creation.data.owner_username_required}<label
						class="grid grid-cols-1 gap-1 sm:col-span-2"
						>{$t('Owner username (exact match)')}<input
							class="input"
							bind:value={ownerUsername}
							required
							maxlength="120"
							autocomplete="username"
						/></label
					>{/if}
				<Button
					type="submit"
					disabled={busy ||
						!name.trim() ||
						(creation.data.owner_username_required && !ownerUsername.trim())}
				>
					{$t('Create workspace')}
				</Button>
			</form>
		</section>
	{:else}<Notice
			>{$t(
				'Workspace creation is restricted by the instance policy. Ask an administrator for access.'
			)}</Notice
		>{/if}
</section>
