<script lang="ts">
	import { afterNavigate, goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { untrack, type Snippet } from 'svelte';
	import Button from '#lib/design/Button.svelte';
	import Icon from '#lib/design/Icon.svelte';
	import Panel from '#lib/design/Panel.svelte';
	import SectionHeader from '#lib/design/SectionHeader.svelte';
	import SectionTab from '#lib/design/SectionTab.svelte';
	import SectionTabs from '#lib/design/SectionTabs.svelte';
	import { msg, ph, t } from 'lingui-for-svelte/macro';
	import type { MessageDescriptor } from '@lingui/core';
	import { setAdminFilters } from './filters';
	import type { AdminFilters, AdminSection } from './queries';
	import { readAdminFilters, adminListParameters, defaultAdminSortDirection } from './list-state';

	let { children }: { children: Snippet } = $props();
	const id = $props.id();

	const labels: Record<AdminSection, MessageDescriptor> = {
		overview: msg`Overview`,
		users: msg`Users`,
		invitations: msg`Invitations`,
		workspaces: msg`Workspaces`,
		audit: msg`Audit`,
		workflows: msg`Workflows`,
		settings: msg`Settings`,
		maintenance: msg`Maintenance`
	};
	const sectionKeys = Object.keys(labels) as AdminSection[];
	const section = $derived.by(() => {
		const candidate = page.url.pathname.split('/').filter(Boolean)[1];
		return sectionKeys.find((key) => key === candidate) ?? 'overview';
	});

	const applied = $derived(readAdminFilters(page.url.searchParams, section));
	const initial = untrack(() => ({ section, filters: applied }));
	let searchInput = $state(initial.filters.search);
	let roleFilter = $state(initial.filters.role);
	let activeFilter = $state(initial.filters.active);
	let actionFilter = $state(initial.filters.action);
	let targetTypeFilter = $state(initial.filters.targetType);
	let workflowStateFilter = $state(initial.filters.workflowState);
	let invitationStateFilter = $state(initial.filters.invitationState);
	let workflowNameFilter = $state(initial.filters.workflowName);
	let workspaceStateFilter = $state(initial.filters.workspaceState);
	let frozenFilter = $state(initial.filters.frozen);
	let ownerActiveFilter = $state(initial.filters.ownerActive);
	const filterFields = [
		'search',
		'role',
		'active',
		'action',
		'targetType',
		'workflowState',
		'invitationState',
		'workflowName',
		'workspaceState',
		'frozen',
		'ownerActive'
	] as const;
	let previousSection = initial.section;
	let previousFilters = initial.filters;
	afterNavigate(({ type }) => {
		const previous = previousFilters;
		// Page-only navigation keeps unsubmitted edits; history explicitly restores the URL.
		if (
			type === 'popstate' ||
			section !== previousSection ||
			filterFields.some((key) => applied[key] !== previous[key])
		) {
			restoreFilterDraft(applied);
		}
		previousSection = section;
		previousFilters = applied;
	});

	function restoreFilterDraft(filters: AdminFilters) {
		searchInput = filters.search;
		roleFilter = filters.role;
		activeFilter = filters.active;
		actionFilter = filters.action;
		targetTypeFilter = filters.targetType;
		workflowStateFilter = filters.workflowState;
		invitationStateFilter = filters.invitationState;
		workflowNameFilter = filters.workflowName;
		workspaceStateFilter = filters.workspaceState;
		frozenFilter = filters.frozen;
		ownerActiveFilter = filters.ownerActive;
	}

	function navigate(filters: AdminFilters, history: 'push' | 'replace' = 'push') {
		const parameters = adminListParameters(filters, section);
		const path = sectionPath(section);
		// Drafts are committed synchronously by Apply/Clear. A delayed navigation must
		// not overwrite edits the user makes after requesting it. History still restores.
		previousFilters = filters;
		void goto(resolve(parameters ? `${path}?${parameters}` : path), {
			reset: false,
			replace: history === 'replace'
		});
	}

	function filters(): AdminFilters {
		return applied;
	}
	function setPage(nextPage: number) {
		navigate({ ...applied, page: nextPage });
	}
	function correctPage(lastPage: number) {
		if (applied.page > lastPage) navigate({ ...applied, page: lastPage }, 'replace');
	}
	function setPageSize(size: number) {
		navigate({ ...applied, pageSize: size, page: 1 });
	}
	function setSort(sort: AdminFilters['sort'], direction: AdminFilters['direction']) {
		navigate({ ...applied, sort, direction, page: 1 });
	}
	setAdminFilters({ filters, setPage, correctPage, setPageSize, setSort });

	const sortOptions: { value: AdminFilters['sort']; label: MessageDescriptor }[] = $derived(
		section === 'users'
			? [
					{ value: 'username', label: msg`Username` },
					{ value: 'created', label: msg`Created` }
				]
			: section === 'invitations'
				? [
						{ value: 'created', label: msg`Created` },
						{ value: 'expires', label: msg`Expires` },
						{ value: 'username', label: msg`Username` }
					]
				: section === 'workspaces'
					? [
							{ value: 'name', label: msg`Name` },
							{ value: 'owner', label: msg`Owner` },
							{ value: 'created', label: msg`Created` }
						]
					: [{ value: 'created', label: msg`Created` }]
	);
	const nextDirection = $derived(applied.direction === 'asc' ? 'desc' : 'asc');
	function orderLabel(order: AdminFilters['direction']) {
		if (['username', 'name', 'owner'].includes(applied.sort))
			return order === 'asc' ? $t`A–Z` : $t`Z–A`;
		if (applied.sort === 'expires') return order === 'asc' ? $t`Earliest first` : $t`Latest first`;
		return order === 'asc' ? $t`Oldest first` : $t`Newest first`;
	}
	const directionHint = $derived(
		$t`Sort order: ${ph({ current: orderLabel(applied.direction) })}. Switch to ${ph({ next: orderLabel(nextDirection) })}.`
	);
	function changeSort(value: string) {
		const option = sortOptions.find((option) => option.value === value);
		if (option) setSort(option.value, defaultAdminSortDirection(option.value));
	}

	function applyFilters(event: SubmitEvent) {
		event.preventDefault();
		const next = {
			...applied,
			page: 1,
			search: searchInput.trim(),
			role: roleFilter,
			active: activeFilter,
			action: actionFilter.trim(),
			targetType: targetTypeFilter.trim(),
			workflowState: workflowStateFilter,
			invitationState: invitationStateFilter,
			workflowName: workflowNameFilter.trim(),
			workspaceState: workspaceStateFilter,
			frozen: frozenFilter,
			ownerActive: ownerActiveFilter
		};
		restoreFilterDraft(next);
		navigate(next);
	}

	function clearFilters() {
		const defaults = readAdminFilters(new URLSearchParams(), section);
		restoreFilterDraft(defaults);
		navigate(defaults);
	}

	function sectionPath(key: AdminSection) {
		return key === 'overview' ? ('admin' as const) : (`admin/${key}` as const);
	}
</script>

<SectionHeader>
	<div>
		<h1>{$t`Administration`}</h1>
		<p class="text-surface-700-300">
			{$t`Users, storage, audit, settings, and durable operations.`}
		</p>
	</div>
</SectionHeader>
<SectionTabs label={$t`Administration sections`}>
	{#each sectionKeys as key (key)}
		<SectionTab href={resolve(sectionPath(key))} current={section === key}
			>{$t(labels[key])}</SectionTab
		>
	{/each}
</SectionTabs>
{#if ['users', 'invitations', 'workspaces', 'audit', 'workflows'].includes(section)}
	<Panel class="mb-4">
		<form class="flex min-w-0 flex-wrap items-end gap-3" onsubmit={applyFilters}>
			{#if section !== 'workflows'}
				<label data-filter-search class="grid min-w-0 grow basis-full grid-cols-1 gap-1 text-sm"
					>{$t`Search`}
					<input class="input h-9 field-sm" type="search" bind:value={searchInput} />
				</label>
			{:else}
				<label data-filter-search class="grid min-w-0 grow basis-full grid-cols-1 gap-1 text-sm"
					>{$t`Workflow name (exact)`}
					<input class="input h-9 field-sm" bind:value={workflowNameFilter} />
				</label>
				<label data-filter-field class="grid min-w-0 grow grid-cols-1 gap-1 text-sm"
					>{$t`State`}
					<select class="select h-9 field-sm" bind:value={workflowStateFilter}>
						<option value="">{$t`Any state`}</option>
						<option value="pending">{$t`Pending`}</option>
						<option value="running">{$t`Running`}</option>
						<option value="succeeded">{$t`Succeeded`}</option>
						<option value="failed">{$t`Failed`}</option>
						<option value="cancelled">{$t`Cancelled`}</option>
					</select>
				</label>
			{/if}
			{#if section === 'users' || section === 'invitations'}
				<label data-filter-field class="grid min-w-0 grow grid-cols-1 gap-1 text-sm"
					>{$t`Role`}
					<select class="select h-9 field-sm" bind:value={roleFilter}>
						<option value="">{$t`All roles`}</option>
						<option value="member">{$t`Member`}</option>
						<option value="administrator">{$t`Administrator`}</option>
					</select>
				</label>
				<label data-filter-field class="grid min-w-0 grow grid-cols-1 gap-1 text-sm"
					>{$t`Status`}
					{#if section === 'users'}
						<select class="select h-9 field-sm" bind:value={activeFilter}>
							<option value="">{$t`Any status`}</option>
							<option value="true">{$t`Active`}</option>
							<option value="false">{$t`Disabled`}</option>
						</select>
					{:else}
						<select class="select h-9 field-sm" bind:value={invitationStateFilter}>
							<option value="">{$t`Any status`}</option>
							<option value="pending">{$t`Pending`}</option>
							<option value="accepted">{$t`Accepted`}</option>
							<option value="revoked">{$t`Revoked`}</option>
							<option value="expired">{$t`Expired`}</option>
						</select>
					{/if}
				</label>
			{:else if section === 'workspaces'}
				<label data-filter-field class="grid min-w-0 grow grid-cols-1 gap-1 text-sm"
					>{$t`State`}
					<select class="select h-9 field-sm" bind:value={workspaceStateFilter}>
						<option value="">{$t`Any state`}</option>
						<option value="active">{$t`Active`}</option>
						<option value="archived">{$t`Archived`}</option>
					</select>
				</label>
				<label data-filter-field class="grid min-w-0 grow grid-cols-1 gap-1 text-sm"
					>{$t`Write freeze`}
					<select class="select h-9 field-sm" bind:value={frozenFilter}>
						<option value="">{$t`Any status`}</option>
						<option value="true">{$t`Frozen`}</option>
						<option value="false">{$t`Not frozen`}</option>
					</select>
				</label>
				<label data-filter-field class="grid min-w-0 grow grid-cols-1 gap-1 text-sm"
					>{$t`Owner account`}
					<select class="select h-9 field-sm" bind:value={ownerActiveFilter}>
						<option value="">{$t`Any status`}</option>
						<option value="true">{$t`Active`}</option>
						<option value="false">{$t`Disabled`}</option>
					</select>
				</label>
			{:else if section === 'audit'}
				<label data-filter-text class="grid min-w-0 grow basis-36 grid-cols-1 gap-1 text-sm"
					>{$t`Action`}
					<input class="input h-9 field-sm" bind:value={actionFilter} />
				</label>
				<label data-filter-text class="grid min-w-0 grow basis-36 grid-cols-1 gap-1 text-sm"
					>{$t`Target type`}
					<input class="input h-9 field-sm" bind:value={targetTypeFilter} />
				</label>
			{/if}
			<div data-filter-actions class="flex min-w-0 grow basis-full flex-wrap items-end gap-3">
				<div data-filter-buttons class="flex grow basis-48 gap-2">
					<Button variant="filled" size="sm" class="h-9 flex-1">{$t`Apply filters`}</Button>
					<Button type="button" size="sm" class="h-9 flex-1" onclick={clearFilters}
						>{$t`Clear filters`}</Button
					>
				</div>
				<div data-filter-sort class="grid min-w-0 grow basis-36 grid-cols-1 gap-1 text-sm">
					<label for={`${id}-sort`}>{$t`Sort By`}</label>
					<div
						role="group"
						aria-label={$t`Sort`}
						class="field-group min-w-0 grid-cols-[minmax(0,1fr)_auto] gap-0"
					>
						<select
							aria-label={$t`Sort By`}
							id={`${id}-sort`}
							class="select h-9 field-sm"
							value={applied.sort}
							onchange={(event) => changeSort(event.currentTarget.value)}
						>
							{#each sortOptions as option (option.value)}
								<option value={option.value}>{$t(option.label)}</option>
							{/each}
						</select>
						<Button
							type="button"
							variant="icon"
							class="-ml-px size-9"
							aria-label={directionHint}
							title={directionHint}
							onclick={() => setSort(applied.sort, nextDirection)}
						>
							<Icon name={applied.direction === 'asc' ? 'arrow-up' : 'arrow-down'} size={16} />
						</Button>
					</div>
				</div>
			</div>
		</form>
	</Panel>
{/if}
{@render children()}

<style>
	[data-filter-field] {
		flex-basis: 8rem;
	}
	[data-filter-sort] {
		min-width: 9.25rem;
	}
	[data-filter-sort] select {
		min-width: 7rem;
	}
	@media (width >= 80rem) {
		[data-filter-search] {
			flex-basis: 12rem;
		}
		[data-filter-field],
		[data-filter-actions],
		[data-filter-buttons],
		[data-filter-sort] {
			flex: 0 1 auto;
		}
		[data-filter-text] {
			flex-grow: 0;
		}
		[data-filter-buttons] :global(button) {
			flex: none;
		}
	}
</style>
