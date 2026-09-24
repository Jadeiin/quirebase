<script lang="ts">
	import { resolve } from '$app/paths';
	import { createQuery } from '@tanstack/svelte-query';
	import Icon from '$lib/design/Icon.svelte';
	import Panel from '$lib/design/Panel.svelte';
	import RichText from '$lib/design/RichText.svelte';
	import { domainLabel } from '$lib/domain-labels';
	import { dashboardQuery } from '$lib/features/dashboard/queries';
	import { dateFormat } from '$lib/format';
	import { t } from '$lib/i18n';
	import { getWorkspaceContext } from '$lib/workspaces/context.svelte';
	import { workspaceHref } from '$lib/workspaces/href';

	const { workspaceId } = getWorkspaceContext();
	const dashboard = createQuery(() => dashboardQuery(workspaceId));
</script>

<div class="mb-8">
	<div>
		<p class="mb-2 text-xs font-bold tracking-[0.12em] text-primary-700-300 uppercase">Quirebase</p>
		<h1 class="mb-2">{$t('Dashboard')}</h1>
		<p class="m-0 max-w-2xl text-surface-700-300">
			{$t('Continue reading or open a research collection.')}
		</p>
	</div>
</div>
{#if dashboard.isPending}<div
		class="grid min-h-56 grid-cols-1 place-items-center text-surface-600-400"
	>
		{$t('Loading dashboard…')}
	</div>
{:else if dashboard.isError}<div
		class="grid min-h-56 grid-cols-1 place-items-center text-error-700-300"
	>
		{$t('Unable to load the dashboard.')}
	</div>
{:else}
	<div class="mb-5 grid grid-cols-1 gap-3 sm:grid-cols-3">
		<Panel
			as="a"
			padding="none"
			class="flex items-center gap-3 p-4 no-underline transition-colors hover:border-surface-400-600"
			href={resolve(workspaceHref(workspaceId, 'library'))}
		>
			<span
				class="grid size-10 grid-cols-1 place-items-center rounded-lg bg-primary-50-950 text-primary-800-200"
				><Icon name="library" size={20} /></span
			>
			<span
				><strong class="block text-xl tabular-nums">{dashboard.data?.new_items.length ?? 0}</strong
				><small class="text-surface-600-400">{$t('recent additions')}</small></span
			>
		</Panel>
		<Panel
			as="a"
			padding="none"
			class="flex items-center gap-3 p-4 no-underline transition-colors hover:border-surface-400-600"
			href={resolve(workspaceHref(workspaceId, 'projects'))}
		>
			<span
				class="grid size-10 grid-cols-1 place-items-center rounded-lg bg-primary-50-950 text-primary-800-200"
				><Icon name="projects" size={20} /></span
			>
			<span
				><strong class="block text-xl tabular-nums">{dashboard.data?.projects.length ?? 0}</strong
				><small class="text-surface-600-400">{$t('visible Projects')}</small></span
			>
		</Panel>
		<Panel
			as="a"
			padding="none"
			class="flex items-center gap-3 p-4 no-underline transition-colors hover:border-surface-400-600"
			href="/account"
		>
			<span
				class="grid size-10 grid-cols-1 place-items-center rounded-lg bg-primary-50-950 text-primary-800-200"
				><Icon name="user" size={20} /></span
			>
			<span
				><strong class="block text-xl tabular-nums">{dashboard.data?.session_count ?? 0}</strong
				><small class="text-surface-600-400">{$t('active sessions')}</small></span
			>
		</Panel>
	</div>
	<div class="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1.35fr)_minmax(18rem,0.65fr)]">
		<div class="grid grid-cols-1 content-start gap-5">
			<Panel padding="none">
				<header class="flex items-center justify-between border-b border-surface-300-700 px-5 py-4">
					<div>
						<p class="m-0 text-xs font-bold tracking-wide text-primary-700-300 uppercase">
							{$t('Reading')}
						</p>
						<h2 class="m-0 mt-1 text-lg">{$t('Continue reading')}</h2>
					</div>
					<a
						class="text-sm font-semibold text-primary-700-300 no-underline hover:text-primary-800-200"
						href={resolve(workspaceHref(workspaceId, 'library'))}>{$t('Open Library')}</a
					>
				</header>
				<div class="divide-y divide-surface-300-700">
					{#each dashboard.data?.recent_items ?? [] as recent (recent.item.id)}
						<a
							class="group grid grid-cols-1 gap-1 px-5 py-4 no-underline transition-colors hover:bg-primary-50-950/60"
							href={resolve(workspaceHref(workspaceId, `item/${recent.item.id}`))}
						>
							<strong class="leading-snug group-hover:text-primary-800-200"
								><RichText html={recent.item.title_html} /></strong
							>
							<span
								class="flex flex-wrap items-center justify-between gap-2 text-xs text-surface-600-400"
								><span>{recent.item.authors || $t('Unknown authors')}</span><span
									>{$dateFormat.format(new Date(recent.last_read_at))}</span
								></span
							>
						</a>
					{:else}
						<div
							class="grid min-h-40 grid-cols-1 place-items-center p-6 text-center text-sm text-surface-600-400"
						>
							{$t('Open an Item to start your reading history.')}
						</div>
					{/each}
				</div>
			</Panel>
			<Panel padding="none">
				<header class="flex items-center justify-between border-b border-surface-300-700 px-5 py-4">
					<div>
						<p class="m-0 text-xs font-bold tracking-wide text-primary-700-300 uppercase">
							{$t('Library')}
						</p>
						<h2 class="m-0 mt-1 text-lg">{$t('Recently added')}</h2>
					</div>
					<a
						class="text-sm font-semibold text-primary-700-300 no-underline"
						href={resolve(workspaceHref(workspaceId, 'import'))}>{$t('Import more')}</a
					>
				</header>
				<div class="divide-y divide-surface-300-700">
					{#each (dashboard.data?.new_items ?? []).slice(0, 5) as item (item.id)}
						<a
							class="group grid grid-cols-1 gap-1 px-5 py-3.5 no-underline hover:bg-primary-50-950/60"
							href={resolve(workspaceHref(workspaceId, `item/${item.id}`))}
						>
							<strong class="line-clamp-2 text-sm leading-snug group-hover:text-primary-800-200"
								><RichText html={item.title_html} /></strong
							>
							<span class="flex flex-wrap justify-between gap-2 text-xs text-surface-600-400"
								><span>{item.authors || $t('Unknown authors')}</span><span
									>{item.publication_date || $t('Date unknown')}</span
								></span
							>
						</a>
					{:else}
						<div class="p-5 text-sm text-surface-600-400">
							{$t('Your library is empty. Import a paper to begin.')}
						</div>
					{/each}
				</div>
			</Panel>
		</div>
		<div class="grid grid-cols-1 content-start gap-5">
			<Panel>
				<div class="mb-4">
					<p class="m-0 text-xs font-bold tracking-wide text-primary-700-300 uppercase">
						{$t('Get started')}
					</p>
					<h2 class="m-0 mt-1 text-lg">{$t('Quick actions')}</h2>
				</div>
				<div class="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
					{#each [{ path: 'import', icon: 'import', title: $t('Import Items'), detail: $t('DOI, files, or PDFs') }, { path: 'discovery', icon: 'search', title: $t('Discover'), detail: $t('Search scholarly sources') }, { path: 'projects', icon: 'projects', title: $t('New Project'), detail: $t('Organize a collection') }, { path: 'library', icon: 'library', title: $t('Search Library'), detail: $t('Find saved research') }] as action (action.path)}
						<a
							class="group grid grid-cols-1 gap-2 rounded-lg border border-surface-300-700 p-3 no-underline hover:border-primary-700-300/40 hover:bg-primary-50-950"
							href={resolve(workspaceHref(workspaceId, action.path))}
						>
							<span class="text-primary-700-300"><Icon name={action.icon} size={18} /></span>
							<span
								><strong class="block text-sm group-hover:text-primary-800-200"
									>{action.title}</strong
								><small class="text-surface-600-400">{action.detail}</small></span
							>
						</a>
					{/each}
				</div>
			</Panel>
			<Panel>
				<div class="mb-4 flex items-center justify-between">
					<h2 class="m-0 text-lg">{$t('Projects')}</h2>
					<a
						class="text-xs font-semibold text-primary-700-300 no-underline"
						href={resolve(workspaceHref(workspaceId, 'projects'))}>{$t('View all')}</a
					>
				</div>
				<div class="grid grid-cols-1 gap-2">
					{#each dashboard.data?.projects ?? [] as project (project.id)}
						<a
							class="flex items-center justify-between gap-3 rounded-lg bg-surface-200-800 px-3.5 py-3 no-underline hover:bg-primary-50-950"
							href={resolve(workspaceHref(workspaceId, `projects/${project.id}`))}
							><strong class="text-sm">{project.name}</strong><span
								class="text-xs text-surface-600-400">{$t(domainLabel(project.visibility))}</span
							></a
						>
					{:else}<p class="m-0 text-sm text-surface-600-400">{$t('No projects yet.')}</p>{/each}
				</div>
			</Panel>
			<section class="rounded-xl border border-surface-300-700 bg-primary-50-950 p-5">
				<h2 class="mb-2 text-lg">{$t('Keep your Library useful')}</h2>
				<p class="mb-3 text-sm text-surface-700-300">
					{$t(
						'Add Tags as you read, group related Items in Projects, and review duplicates only when needed.'
					)}
				</p>
				<a
					class="text-sm font-semibold text-primary-800-200 no-underline"
					href={resolve(workspaceHref(workspaceId, 'tools'))}>{$t('Open Library tools')} →</a
				>
			</section>
		</div>
	</div>
{/if}
