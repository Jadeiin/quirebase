<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import Pagination from '#lib/design/Pagination.svelte';
	import AdminSectionState from '#lib/features/admin/AdminSectionState.svelte';
	import AdminWorkflows from '#lib/features/admin/AdminWorkflows.svelte';
	import { getAdminFilters } from '#lib/features/admin/filters.js';
	import { adminWorkflowsQuery } from '#lib/features/admin/queries.js';
	import { msg, t } from '#lib/i18n.js';

	const { filters, setPage, setPageSize } = getAdminFilters();
	const workflows = createQuery(() => adminWorkflowsQuery(filters(), true));
	$effect(() => {
		if (workflows.isFetching || !workflows.data) return;
		const lastPage = Math.max(1, Math.ceil(workflows.data.total / filters().pageSize));
		if (filters().page > lastPage) setPage(lastPage);
	});
</script>

<AdminSectionState
	loading={workflows.isPending}
	failed={workflows.isError}
	label={msg('Workflows')}
>
	<AdminWorkflows workflows={workflows.data!.items} />
	<Pagination
		page={filters().page}
		pageSize={filters().pageSize}
		pageCount={Math.max(1, Math.ceil((workflows.data?.total ?? 0) / filters().pageSize))}
		total={workflows.data?.total ?? 0}
		busy={workflows.isFetching}
		label={$t('Administration pages')}
		onPage={setPage}
		onPageSize={setPageSize}
	/>
</AdminSectionState>
