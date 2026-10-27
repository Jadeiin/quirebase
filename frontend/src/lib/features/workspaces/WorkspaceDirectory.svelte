<script lang="ts">
	import { resolve } from '$app/paths';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import { createQuery } from '@tanstack/svelte-query';
	import Button from '#lib/design/Button.svelte';
	import Panel from '#lib/design/Panel.svelte';
	import Badge from '#lib/design/Badge.svelte';
	import Pagination from '#lib/design/Pagination.svelte';
	import Notice from '#lib/design/Notice.svelte';
	import { t } from 'lingui-for-svelte/macro';
	import { domainLabel } from '#lib/domain-labels.js';
	import { workspaceHref } from '#lib/workspaces/href.js';
	import {
		defaultWorkspacePreference,
		setDefaultWorkspacePreference
	} from '#lib/workspaces/preference.js';
	import {
		workspaceCreationAvailabilityQuery,
		workspaceListQuery
	} from '#lib/workspaces/queries.js';
	import WorkspaceCreateDialog from './WorkspaceCreateDialog.svelte';
	import ReceivedInvitations from './ReceivedInvitations.svelte';
	import { readWorkspaceListState, workspaceListParameters } from './list-state';

	const listing = $derived(readWorkspaceListState(page.url.searchParams));
	const workspaces = createQuery(() =>
		workspaceListQuery((listing.page - 1) * listing.pageSize, listing.search, listing.pageSize)
	);
	const creation = createQuery(() => workspaceCreationAvailabilityQuery());
	const lastPage = $derived(
		Math.max(1, Math.ceil((workspaces.data?.total ?? 0) / listing.pageSize))
	);
	let createOpen = $state(false);
	let notice = $state('');
	let defaultWorkspaceId = $state<string | null>(null);
	onMount(() => {
		defaultWorkspaceId = defaultWorkspacePreference();
	});
	function navigate(search: string, nextPage = 1, size = listing.pageSize, replace = false) {
		const parameters = workspaceListParameters(search, nextPage, size, page.url.search);
		void goto(parameters ? resolve(`workspace?${parameters}`) : resolve('workspace'), {
			reset: false,
			replaceState: replace
		});
	}
	$effect(() => {
		if (workspaces.isSuccess && !workspaces.isFetching && listing.page > lastPage)
			navigate(listing.search, lastPage, listing.pageSize, true);
	});
</script>

<svelte:head><title>{$t`Workspaces · Quirebase`}</title></svelte:head>
<section class="mx-auto grid w-full max-w-5xl min-w-0 grid-cols-1 gap-6">
	<header class="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
		<div class="grid min-w-0 grid-cols-1 gap-2">
			<h1 class="text-3xl font-bold">{$t`My workspaces`}</h1>
			<p class="text-surface-700-300">
				{$t`Choose a workspace to open its library and projects.`}
			</p>
		</div>
		{#if creation.data?.allowed}<Button
				variant="filled"
				class="shrink-0 self-start"
				onclick={() => {
					notice = '';
					createOpen = true;
				}}>{$t`Create workspace`}</Button
			>{/if}
	</header>
	<ReceivedInvitations />
	{#if notice}<Notice variant="success">{notice}</Notice>{/if}
	{#if creation.isError}<Notice variant="error"
			>{$t`Unable to check Workspace creation permissions. Refresh and try again.`}
			<Button onclick={() => void creation.refetch()} disabled={creation.isFetching}
				>{$t`Retry`}</Button
			></Notice
		>{/if}
	<label class="grid max-w-xl grid-cols-1 gap-1"
		>{$t`Search workspaces`}<input
			class="input"
			value={listing.search}
			oninput={(event) => navigate(event.currentTarget.value, 1, listing.pageSize, true)}
		/></label
	>
	{#if workspaces.isPending}<p class="text-surface-700-300">{$t`Loading workspaces…`}</p>
	{:else if workspaces.isError}<Notice variant="error"
			>{$t`Unable to load workspaces.`}
			<Button disabled={workspaces.isFetching} onclick={() => void workspaces.refetch()}
				>{$t`Retry`}</Button
			></Notice
		>
	{:else if workspaces.data?.items.length}
		<div class="grid grid-cols-1 gap-3 md:grid-cols-2">
			{#each workspaces.data.items as workspace (workspace.id)}
				<Panel
					as="a"
					href={resolve(workspaceHref(workspace.id))}
					class="group flex min-h-28 items-center justify-between gap-4 text-inherit no-underline transition-colors hover:border-primary-500 hover:bg-primary-50-950 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-500"
					onclick={() => {
						setDefaultWorkspacePreference(workspace.id);
						defaultWorkspaceId = workspace.id;
					}}
				>
					<span class="grid min-w-0 grid-cols-1 gap-2"
						><strong class="truncate text-lg">{workspace.name}</strong><span
							class="text-sm text-surface-700-300"
							>{$t(domainLabel(workspace.current_role))} · {$t(domainLabel(workspace.state))}</span
						></span
					>
					<span
						class="grid shrink-0 grid-cols-1 justify-items-end gap-2 text-sm font-semibold text-primary-700-300"
						>{#if workspace.id === defaultWorkspaceId}<Badge variant="primary">{$t`Default`}</Badge
							>{/if}<span class="group-hover:underline">{$t`Open Workspace`} →</span></span
					>
				</Panel>
			{/each}
		</div>
	{:else if listing.search}
		<Notice
			>{$t`No matching workspaces.`}
			<Button onclick={() => navigate('')}>{$t`Clear search`}</Button></Notice
		>
	{:else}
		<Notice>{$t`No Workspaces yet.`}</Notice>
		{#if creation.data && !creation.data.allowed}<p class="text-sm text-surface-700-300">
				{$t`Workspace creation is restricted by the instance policy. Ask an administrator for access.`}
			</p>{/if}
	{/if}
	{#if workspaces.isSuccess}<Pagination
			page={listing.page}
			pageCount={lastPage}
			pageSize={listing.pageSize}
			total={workspaces.data.total}
			onPage={(next) => navigate(listing.search, next)}
			onPageSize={(size) => navigate(listing.search, 1, size)}
			busy={workspaces.isFetching}
			label={$t`Workspaces`}
		/>{/if}
</section>
{#if creation.data?.allowed}<WorkspaceCreateDialog
		bind:open={createOpen}
		availability={creation.data}
		onCreated={(message) => (notice = message)}
	/>{/if}
