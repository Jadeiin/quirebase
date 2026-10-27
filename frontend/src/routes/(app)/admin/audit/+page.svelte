<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import Pagination from '#lib/design/Pagination.svelte';
	import AdminAudit from '#lib/features/admin/AdminAudit.svelte';
	import AdminSectionState from '#lib/features/admin/AdminSectionState.svelte';
	import { getAdminFilters } from '#lib/features/admin/filters.js';
	import { adminAuditQuery } from '#lib/features/admin/queries.js';
	import { msg, t } from 'lingui-for-svelte/macro';

	const { filters, setPage, correctPage, setPageSize } = getAdminFilters();
	const audit = createQuery(() => adminAuditQuery(filters(), true));
	const pageCount = $derived(
		audit.data?.total && audit.data.limit
			? Math.max(1, Math.ceil(audit.data.total / audit.data.limit))
			: 1
	);
	$effect(() => {
		if (!audit.isSuccess || audit.isFetching || !audit.data) return;
		correctPage(pageCount);
	});
</script>

<AdminSectionState
	available={audit.data != null}
	error={audit.error}
	busy={audit.isFetching}
	onRetry={() => void audit.refetch()}
	loading={audit.isPending}
	failed={audit.isError}
	label={msg`Audit`}
>
	<AdminAudit
		events={audit.data!.items}
		onRefresh={() => void audit.refetch()}
		busy={audit.isFetching}
	/>
	<Pagination
		page={filters().page}
		{pageCount}
		pageSize={filters().pageSize}
		total={audit.data?.total ?? 0}
		busy={audit.isFetching}
		onPageSize={setPageSize}
		label={$t`Administration pages`}
		onPage={setPage}
	/>
</AdminSectionState>
