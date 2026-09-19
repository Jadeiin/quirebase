<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import Pagination from '$lib/design/Pagination.svelte';
	import AdminProjects from '$lib/features/admin/AdminProjects.svelte';
	import AdminSectionState from '$lib/features/admin/AdminSectionState.svelte';
	import { getAdminFilters } from '$lib/features/admin/filters';
	import { adminProjectsQuery } from '$lib/features/admin/queries';
	import { msg, t } from '$lib/i18n';

	const { filters, setPage } = getAdminFilters();
	const projects = createQuery(() => adminProjectsQuery(filters(), true));
	const pageCount = $derived(
		projects.data?.total && projects.data.per_page
			? Math.max(1, Math.ceil(projects.data.total / projects.data.per_page))
			: 1
	);
</script>

<AdminSectionState loading={projects.isPending} failed={projects.isError} label={msg('Projects')}>
	<AdminProjects projects={projects.data!.projects} />
	{#if pageCount > 1}
		<Pagination
			page={filters().page}
			{pageCount}
			label={$t('Administration pages')}
			onPage={setPage}
		/>
	{/if}
</AdminSectionState>
