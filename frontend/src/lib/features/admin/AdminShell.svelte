<script lang="ts">
	import { afterNavigate, goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { untrack, type Snippet } from 'svelte';
	import Button from '#lib/design/Button.svelte';
	import Panel from '#lib/design/Panel.svelte';
	import SectionHeader from '#lib/design/SectionHeader.svelte';
	import SectionTab from '#lib/design/SectionTab.svelte';
	import SectionTabs from '#lib/design/SectionTabs.svelte';
	import { msg, t, type MessageKey } from '#lib/i18n.js';
	import { setAdminFilters } from './filters';
	import type { AdminFilters, AdminSection } from './queries';
	import { readAdminFilters, adminListParameters } from './list-state';

	let { children }: { children: Snippet } = $props();

	const labels: Record<AdminSection, MessageKey> = {
		overview: msg('Overview'),
		users: msg('Users'),
		invitations: msg('Invitations'),
		workspaces: msg('Workspaces'),
		audit: msg('Audit'),
		workflows: msg('Workflows'),
		settings: msg('Settings'),
		maintenance: msg('Maintenance')
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
	const filterFields = [
		'search',
		'role',
		'active',
		'action',
		'targetType',
		'workflowState'
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
	}

	function navigate(filters: AdminFilters, history: 'push' | 'replace' = 'push') {
		const parameters = adminListParameters(filters, section);
		const path = sectionPath(section);
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
	setAdminFilters({ filters, setPage, correctPage, setPageSize });

	function applyFilters(event: SubmitEvent) {
		event.preventDefault();
		navigate({
			...applied,
			page: 1,
			search: searchInput.trim(),
			role: roleFilter,
			active: activeFilter,
			action: actionFilter.trim(),
			targetType: targetTypeFilter.trim(),
			workflowState: workflowStateFilter
		});
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
		<h1>{$t('Administration')}</h1>
		<p class="text-surface-700-300">
			{$t('Users, storage, audit, settings, and durable operations.')}
		</p>
	</div>
</SectionHeader>
<SectionTabs label={$t('Administration sections')}>
	{#each sectionKeys as key (key)}
		<SectionTab href={resolve(sectionPath(key))} current={section === key}
			>{$t(labels[key])}</SectionTab
		>
	{/each}
</SectionTabs>
{#if ['users', 'workspaces', 'audit', 'workflows'].includes(section)}
	<Panel as="form" class="mb-4 flex flex-wrap items-end gap-2" onsubmit={applyFilters}>
		{#if section !== 'workflows'}
			<label class="grow basis-64"
				>{$t('Search')}<input class="input h-8" bind:value={searchInput} /></label
			>
		{:else}
			<label
				>{$t('State')}<select class="input h-8 w-auto min-w-36" bind:value={workflowStateFilter}
					><option value="">{$t('Any state')}</option><option value="pending"
						>{$t('Pending')}</option
					><option value="running">{$t('Running')}</option><option value="succeeded"
						>{$t('Succeeded')}</option
					><option value="failed">{$t('Failed')}</option><option value="cancelled"
						>{$t('Cancelled')}</option
					></select
				></label
			>
		{/if}
		{#if section === 'users'}
			<label
				>{$t('Role')}<select class="input h-8 w-auto min-w-36" bind:value={roleFilter}
					><option value="">{$t('All roles')}</option><option value="member">{$t('Member')}</option
					><option value="administrator">{$t('Administrator')}</option></select
				></label
			>
			<label
				>{$t('Status')}<select class="input h-8 w-auto min-w-36" bind:value={activeFilter}
					><option value="">{$t('Any status')}</option><option value="true">{$t('Active')}</option
					><option value="false">{$t('Disabled')}</option></select
				></label
			>
		{:else if section === 'audit'}
			<label
				>{$t('Action')}<input class="input h-8 w-auto min-w-36" bind:value={actionFilter} /></label
			>
			<label
				>{$t('Target type')}<input
					class="input h-8 w-auto min-w-36"
					bind:value={targetTypeFilter}
				/></label
			>
		{/if}
		<Button variant="filled">{$t('Apply filters')}</Button>
		<Button type="button" onclick={clearFilters}>{$t('Clear filters')}</Button>
	</Panel>
{/if}
{@render children()}
