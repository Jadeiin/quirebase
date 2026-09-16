<script lang="ts">
	import { resolve } from '$app/paths';
	import { createQuery } from '@tanstack/svelte-query';
	import { apiRequest, type ItemSummary } from '$lib/api/client';
	import RichText from '$lib/design/RichText.svelte';
	import { domainLabel } from '$lib/domain-labels';
	import { t } from '$lib/i18n';

	type DashboardView = {
		new_items: ItemSummary[];
		recent_items: Array<{ item: ItemSummary; last_read_at: string }>;
		projects: Array<{ id: string; name: string; visibility: string }>;
		session_count: number;
	};
	const dashboard = createQuery(() => ({
		queryKey: ['dashboard'],
		queryFn: () => apiRequest<DashboardView>('/dashboard')
	}));
</script>

<div class="mb-8">
	<div>
		<p class="mb-2 text-xs font-bold tracking-[0.12em] text-accent uppercase">Quirebase</p>
		<h1 class="mb-2">{$t('Dashboard')}</h1>
		<p class="m-0 max-w-2xl text-secondary">
			{$t('Continue reading or open a research collection.')}
		</p>
	</div>
</div>
{#if dashboard.isPending}<div class="grid min-h-56 place-items-center text-muted">
		{$t('Loading dashboard…')}
	</div>
{:else if dashboard.isError}<div class="grid min-h-56 place-items-center text-danger">
		{$t('Unable to load the dashboard.')}
	</div>
{:else}
	<div class="grid gap-5 lg:grid-cols-[minmax(0,1.35fr)_minmax(18rem,0.65fr)]">
		<section class="overflow-hidden rounded-xl border border-line bg-raised shadow-sm">
			<header class="flex items-center justify-between border-b border-line px-5 py-4">
				<div>
					<p class="m-0 text-xs font-bold tracking-wide text-accent uppercase">{$t('Reading')}</p>
					<h2 class="m-0 mt-1 text-lg">{$t('Continue reading')}</h2>
				</div>
				<a
					class="text-sm font-semibold text-accent no-underline hover:text-accent-strong"
					href={resolve('/library')}>{$t('Open Library')}</a
				>
			</header>
			<div class="divide-y divide-line">
				{#each dashboard.data?.recent_items ?? [] as recent (recent.item.id)}
					<a
						class="group grid gap-1 px-5 py-4 no-underline transition-colors hover:bg-accent-soft/60"
						href={resolve('/(app)/item/[itemId]', { itemId: recent.item.id })}
					>
						<strong class="leading-snug group-hover:text-accent-strong"
							><RichText html={recent.item.title_html} /></strong
						>
						<span class="flex flex-wrap items-center justify-between gap-2 text-xs text-muted"
							><span>{recent.item.authors || $t('Unknown authors')}</span><span
								>{new Date(recent.last_read_at).toLocaleDateString()}</span
							></span
						>
					</a>
				{:else}
					<div class="grid min-h-40 place-items-center p-6 text-center text-sm text-muted">
						{$t('Open an Item to start your reading history.')}
					</div>
				{/each}
			</div>
		</section>
		<div class="grid content-start gap-5">
			<section class="rounded-xl border border-line bg-raised p-5 shadow-sm">
				<div class="mb-4 flex items-center justify-between">
					<h2 class="m-0 text-lg">{$t('Projects')}</h2>
					<a class="text-xs font-semibold text-accent no-underline" href={resolve('/projects')}
						>{$t('View all')}</a
					>
				</div>
				<div class="grid gap-2">
					{#each dashboard.data?.projects ?? [] as project (project.id)}
						<a
							class="flex items-center justify-between gap-3 rounded-lg bg-muted-surface px-3.5 py-3 no-underline hover:bg-accent-soft"
							href={resolve('/(app)/projects/[projectId]', { projectId: project.id })}
							><strong class="text-sm">{project.name}</strong><span class="text-xs text-muted"
								>{$t(domainLabel(project.visibility))}</span
							></a
						>
					{:else}<p class="m-0 text-sm text-muted">{$t('No projects yet.')}</p>{/each}
				</div>
			</section>
			<section class="rounded-xl border border-line bg-raised p-5 shadow-sm">
				<h2 class="m-0 mb-3 text-lg">{$t('New Items')}</h2>
				<div class="grid gap-3">
					{#each (dashboard.data?.new_items ?? []).slice(0, 4) as item (item.id)}
						<a
							class="line-clamp-2 text-sm leading-snug font-semibold no-underline hover:text-accent-strong"
							href={resolve('/(app)/item/[itemId]', { itemId: item.id })}
							><RichText html={item.title_html} /></a
						>
					{:else}<p class="m-0 text-sm text-muted">
							{$t('Your library is empty. Import a paper to begin.')}
						</p>{/each}
				</div>
			</section>
		</div>
	</div>
{/if}
