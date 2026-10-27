<script lang="ts">
	import { resolve } from '$app/paths';
	import { onMount } from 'svelte';
	import { createQuery } from '@tanstack/svelte-query';
	import Button from '#lib/design/Button.svelte';
	import Icon from '#lib/design/Icon.svelte';
	import QueryError from '#lib/design/QueryError.svelte';
	import { libraryHref } from '#lib/features/library/filters.js';
	import { projectListQuery } from '#lib/features/projects/queries.js';
	import { activeLocale } from '#lib/locale.js';
	import { t } from 'lingui-for-svelte/macro';
	import { workspaceHref, type WorkspacePath } from '#lib/workspaces/href.js';
	import { setDefaultWorkspacePreference } from '#lib/workspaces/preference.js';
	import { workspaceListQuery, workspaceQuery } from '#lib/workspaces/queries.js';
	import { quickPageLinks } from './quick-navigation.js';

	let {
		workspaceId,
		administration,
		onNavigate,
		onReady
	}: {
		workspaceId?: string;
		administration: boolean;
		onNavigate: () => void;
		onReady: (input: HTMLInputElement) => void;
	} = $props();
	let search = $state('');
	let debouncedQuery = $state('');
	let workspacePage = $state(1);
	let projectPage = $state(1);
	let searchInput = $state<HTMLInputElement>();
	let results = $state<HTMLDivElement>();
	let workspaceHeading = $state<HTMLHeadingElement>();
	let projectHeading = $state<HTMLHeadingElement>();
	const query = $derived(search.trim());
	const debouncing = $derived(query !== debouncedQuery);
	$effect(() => {
		const next = query;
		if (next === debouncedQuery) return;
		const timer = setTimeout(() => {
			debouncedQuery = next;
			workspacePage = projectPage = 1;
		}, 200);
		return () => clearTimeout(timer);
	});
	onMount(() => {
		if (searchInput) onReady(searchInput);
	});

	const current = createQuery(() => workspaceQuery(workspaceId ?? ''));
	const availableWorkspaceId = $derived(
		current.isSuccess && current.data?.id === workspaceId ? workspaceId : undefined
	);
	const workspaces = createQuery(() =>
		workspaceListQuery((workspacePage - 1) * 25, debouncedQuery)
	);
	const projects = createQuery(() => ({
		...projectListQuery(availableWorkspaceId ?? '', 'all', (projectPage - 1) * 25, debouncedQuery),
		enabled: Boolean(availableWorkspaceId),
		retry: false
	}));
	const workspacePages = $derived(Math.max(1, Math.ceil((workspaces.data?.total ?? 0) / 25)));
	const projectPages = $derived(Math.max(1, Math.ceil((projects.data?.total ?? 0) / 25)));
	$effect(() => {
		if (workspaces.isSuccess && !workspaces.isFetching && workspacePage > workspacePages)
			workspacePage = workspacePages;
	});
	$effect(() => {
		if (projects.isSuccess && !projects.isFetching && projectPage > projectPages)
			projectPage = projectPages;
	});
	const pages = $derived(
		quickPageLinks(availableWorkspaceId, administration).filter((link) =>
			$t(link.label)
				.toLocaleLowerCase($activeLocale)
				.includes(query.toLocaleLowerCase($activeLocale))
		)
	);

	function activate(event: MouseEvent, nextWorkspaceId?: string) {
		if (
			event.defaultPrevented ||
			event.button !== 0 ||
			event.metaKey ||
			event.ctrlKey ||
			event.altKey ||
			event.shiftKey
		)
			return;
		if (nextWorkspaceId && nextWorkspaceId !== workspaceId) {
			try {
				setDefaultWorkspacePreference(nextWorkspaceId);
			} catch {
				// Navigation remains available when preference storage is unavailable.
			}
		}
		onNavigate();
	}

	function navigateResults(event: KeyboardEvent) {
		if (
			event.defaultPrevented ||
			event.isComposing ||
			event.keyCode === 229 ||
			event.metaKey ||
			event.ctrlKey ||
			event.altKey ||
			event.shiftKey
		)
			return;
		const links = [
			...(results?.querySelectorAll<HTMLAnchorElement>('a[data-quick-navigation-result]') ?? [])
		];
		const origin = event.currentTarget;
		let target: HTMLElement | undefined;
		if (origin === searchInput) {
			if (event.key === 'ArrowDown') target = links[0];
			else if (event.key === 'ArrowUp') target = links.at(-1);
			else if (event.key === 'Enter' && links[0]) {
				event.preventDefault();
				links[0].click();
				return;
			}
		} else {
			const index = links.indexOf(origin as HTMLAnchorElement);
			if (event.key === 'ArrowDown') target = links[Math.min(index + 1, links.length - 1)];
			else if (event.key === 'ArrowUp') target = index > 0 ? links[index - 1] : searchInput;
			else if (event.key === 'Home') target = links[0];
			else if (event.key === 'End') target = links.at(-1);
		}
		if (target) {
			event.preventDefault();
			target.focus();
			target.scrollIntoView({ block: 'nearest' });
		}
	}
</script>

{#snippet resultLink(
	href: WorkspacePath | 'workspace' | 'account' | 'admin',
	label: string,
	icon: string,
	nextWorkspaceId?: string
)}
	<a
		href={resolve(href)}
		data-quick-navigation-result
		class="flex min-w-0 items-center gap-3 rounded-lg px-3 py-2 no-underline hover:bg-primary-50-950 focus:bg-primary-50-950"
		onclick={(event) => activate(event, nextWorkspaceId)}
		onkeydown={navigateResults}
	>
		<span class="shrink-0 text-surface-600-400"><Icon name={icon} size={18} /></span>
		<span class="min-w-0 break-words">{label}</span>
	</a>
{/snippet}

{#snippet paging(page: number, pageCount: number, busy: boolean, onPage: (page: number) => void)}
	{#if pageCount > 1 || page > 1}
		<div class="mt-2 flex flex-wrap items-center justify-between gap-2 px-3">
			<Button size="sm" disabled={busy || page <= 1} onclick={() => onPage(page - 1)}
				>{$t`Previous page`}</Button
			>
			<span class="text-xs text-surface-600-400" aria-live="polite"
				>{$t`Page ${page} of ${pageCount}`}</span
			>
			<Button size="sm" disabled={busy || page >= pageCount} onclick={() => onPage(page + 1)}
				>{$t`Next page`}</Button
			>
		</div>
	{/if}
{/snippet}

<label class="sr-only" for="quick-navigation-search">
	{$t`Search pages, Workspaces, or Projects`}
</label>
<input
	id="quick-navigation-search"
	bind:this={searchInput}
	bind:value={search}
	class="mt-4 input"
	placeholder={$t`Search pages, Workspaces, or Projects`}
	type="search"
	autocomplete="off"
	onkeydown={navigateResults}
/>

<div bind:this={results} class="mt-4 grid grid-cols-1 gap-5">
	<section aria-label={$t`Pages and settings`}>
		<h3 class="px-3 text-xs font-bold text-surface-600-400">{$t`Pages and settings`}</h3>
		<div class="mt-1">
			{#each pages as link (link.id)}
				{@render resultLink(link.href, $t(link.label), link.icon)}
			{:else}
				{#if !availableWorkspaceId || !query}
					<p class="px-3 py-2 text-sm text-surface-600-400">{$t`No matching pages.`}</p>
				{/if}
			{/each}
			{#if availableWorkspaceId && query}
				{@render resultLink(
					libraryHref(availableWorkspaceId, { query }),
					$t`Search Library for ${query}`,
					'search'
				)}
			{/if}
		</div>
	</section>

	<section aria-label={$t`Workspaces`}>
		<h3
			bind:this={workspaceHeading}
			tabindex="-1"
			class="px-3 text-xs font-bold text-surface-600-400"
		>
			{$t`Workspaces`}
		</h3>
		{#if debouncing || (workspaces.isPending && workspaces.fetchStatus !== 'paused')}
			<p class="px-3 py-2 text-sm text-surface-600-400" role="status">
				{$t`Loading workspaces…`}
			</p>
		{:else if workspaces.isError || workspaces.fetchStatus === 'paused'}
			<QueryError
				message={$t`Unable to load workspaces.`}
				busy={workspaces.isFetching}
				onRetry={() => void workspaces.refetch()}
			/>
		{:else if workspaces.data}
			<div class="mt-1">
				{#each workspaces.data.items as workspace (workspace.id)}
					{@render resultLink(workspaceHref(workspace.id), workspace.name, 'panel', workspace.id)}
				{:else}
					<p class="px-3 py-2 text-sm text-surface-600-400">{$t`No workspaces available`}</p>
				{/each}
			</div>
			{@render paging(workspacePage, workspacePages, workspaces.isFetching, (page) => {
				workspacePage = page;
				workspaceHeading?.focus();
			})}
		{/if}
	</section>

	{#if workspaceId}
		<section aria-label={$t`Projects`}>
			<h3
				bind:this={projectHeading}
				tabindex="-1"
				class="px-3 text-xs font-bold text-surface-600-400"
			>
				{$t`Projects`}
			</h3>
			{#if current.isError || current.fetchStatus === 'paused'}
				<QueryError
					message={$t`Unable to load workspace.`}
					busy={current.isFetching}
					onRetry={() => void current.refetch()}
				/>
			{:else if !availableWorkspaceId || debouncing || (projects.isPending && projects.fetchStatus !== 'paused')}
				<p class="px-3 py-2 text-sm text-surface-600-400" role="status">
					{$t`Loading Projects…`}
				</p>
			{:else if projects.isError || projects.fetchStatus === 'paused'}
				<QueryError
					message={$t`Unable to load Projects.`}
					busy={projects.isFetching}
					onRetry={() => void projects.refetch()}
				/>
			{:else if projects.data}
				<p class="mb-1 px-3 text-xs break-words text-surface-600-400">{current.data?.name}</p>
				<div>
					{#each projects.data.items as project (project.id)}
						{@render resultLink(
							workspaceHref(availableWorkspaceId, `projects/${encodeURIComponent(project.id)}`),
							project.name,
							'projects'
						)}
					{:else}
						<p class="px-3 py-2 text-sm text-surface-600-400">{$t`No matching Projects.`}</p>
					{/each}
				</div>
				{@render paging(projectPage, projectPages, projects.isFetching, (page) => {
					projectPage = page;
					projectHeading?.focus();
				})}
			{/if}
		</section>
	{/if}
</div>
