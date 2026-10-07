<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import Pagination from '#lib/design/Pagination.svelte';
	import AdminAudit from '#lib/features/admin/AdminAudit.svelte';
	import AdminSectionState from '#lib/features/admin/AdminSectionState.svelte';
	import { getAdminFilters } from '#lib/features/admin/filters.js';
	import { adminAuditQuery } from '#lib/features/admin/queries.js';
	import { msg, t } from '#lib/i18n.js';

	const { filters, setPage } = getAdminFilters();
	const audit = createQuery(() => adminAuditQuery(filters(), true));
	const pageCount = $derived(
		audit.data?.total && audit.data.limit
			? Math.max(1, Math.ceil(audit.data.total / audit.data.limit))
			: 1
	);
</script>

<AdminSectionState loading={audit.isPending} failed={audit.isError} label={msg('Audit')}>
	<AdminAudit events={audit.data!.items} />
	{#if pageCount > 1}
		<Pagination
			page={filters().page}
			{pageCount}
			label={$t('Administration pages')}
			onPage={setPage}
		/>
	{/if}
</AdminSectionState>
