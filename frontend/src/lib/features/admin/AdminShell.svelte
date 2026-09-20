<script lang="ts">
	import { beforeNavigate } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import type { Snippet } from 'svelte';
	import Button from '$lib/design/Button.svelte';
	import Panel from '$lib/design/Panel.svelte';
	import SectionHeader from '$lib/design/SectionHeader.svelte';
	import SectionTab from '$lib/design/SectionTab.svelte';
	import SectionTabs from '$lib/design/SectionTabs.svelte';
	import { msg, t, type MessageKey } from '$lib/i18n';
	import { setAdminFilters } from './filters';
	import type { AdminFilters, AdminSection } from './queries';

	let { children } = $props<{ children: Snippet }>();

	const labels: Record<AdminSection, MessageKey> = {
		overview: msg('Overview'),
		users: msg('Users'),
		projects: msg('Projects'),
		items: msg('Items'),
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

	let searchInput = $state('');
	let filterA = $state('');
	let filterB = $state('');
	let appliedSearch = $state('');
	let appliedFilterA = $state('');
	let appliedFilterB = $state('');
	let adminPage = $state(1);

	function filters(): AdminFilters {
		return {
			page: adminPage,
			search: appliedSearch,
			filterA: appliedFilterA,
			filterB: appliedFilterB
		};
	}
	function setPage(nextPage: number) {
		adminPage = nextPage;
	}
	setAdminFilters({ filters, setPage });

	function applyFilters(event: SubmitEvent) {
		event.preventDefault();
		adminPage = 1;
		appliedSearch = searchInput.trim();
		appliedFilterA = filterA;
		appliedFilterB = filterB;
	}

	function clearFilters() {
		searchInput = '';
		filterA = '';
		filterB = '';
		appliedSearch = '';
		appliedFilterA = '';
		appliedFilterB = '';
		adminPage = 1;
	}
	beforeNavigate(() => clearFilters());

	function sectionPath(key: AdminSection) {
		return key === 'overview' ? ('/admin' as const) : (`/admin/${key}` as const);
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
{#if ['users', 'projects', 'items', 'audit', 'workflows'].includes(section)}
	<Panel as="form" class="mb-4 flex flex-wrap items-end gap-2" onsubmit={applyFilters}>
		{#if section !== 'workflows'}
			<label class="grow basis-64"
				>{$t('Search')}<input class="input" bind:value={searchInput} /></label
			>
		{:else}
			<label
				>{$t('State')}<select class="input w-auto min-w-36" bind:value={filterA}
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
				>{$t('Role')}<select class="input w-auto min-w-36" bind:value={filterA}
					><option value="">{$t('All roles')}</option><option value="member">{$t('Member')}</option
					><option value="administrator">{$t('Administrator')}</option></select
				></label
			>
			<label
				>{$t('Status')}<select class="input w-auto min-w-36" bind:value={filterB}
					><option value="">{$t('Any status')}</option><option value="true">{$t('Active')}</option
					><option value="false">{$t('Disabled')}</option></select
				></label
			>
		{:else if section === 'projects'}
			<label
				>{$t('State')}<select class="input w-auto min-w-36" bind:value={filterA}
					><option value="">{$t('Any state')}</option><option value="active">{$t('Active')}</option
					><option value="archived">{$t('Archived')}</option></select
				></label
			>
			<label
				>{$t('Visibility')}<select class="input w-auto min-w-36" bind:value={filterB}
					><option value="">{$t('Any visibility')}</option><option value="private"
						>{$t('Private')}</option
					><option value="public">{$t('Public')}</option></select
				></label
			>
		{:else if section === 'items'}
			<label
				>{$t('PDF availability')}<select class="input w-auto min-w-36" bind:value={filterA}
					><option value="">{$t('Any')}</option><option value="true">{$t('Has PDF')}</option><option
						value="false">{$t('Without PDF')}</option
					></select
				></label
			>
		{:else if section === 'audit'}
			<label>{$t('Action')}<input class="input w-auto min-w-36" bind:value={filterA} /></label>
			<label>{$t('Target type')}<input class="input w-auto min-w-36" bind:value={filterB} /></label>
		{/if}
		<Button variant="filled">{$t('Apply filters')}</Button>
		<Button type="button" onclick={clearFilters}>{$t('Clear filters')}</Button>
	</Panel>
{/if}
{@render children()}
