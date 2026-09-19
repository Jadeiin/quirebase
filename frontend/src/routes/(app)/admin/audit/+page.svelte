<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import Pagination from '$lib/design/Pagination.svelte';
	import AdminAudit from '$lib/features/admin/AdminAudit.svelte';
	import AdminSectionState from '$lib/features/admin/AdminSectionState.svelte';
	import { getAdminFilters } from '$lib/features/admin/filters';
	import { adminAuditQuery } from '$lib/features/admin/queries';
	import { msg, t } from '$lib/i18n';

	const { filters, setPage } = getAdminFilters();
	const audit = createQuery(() => adminAuditQuery(filters(), true));
	const pageCount = $derived(
		audit.data?.total && audit.data.per_page
			? Math.max(1, Math.ceil(audit.data.total / audit.data.per_page))
			: 1
	);
</script>

<AdminSectionState loading={audit.isPending} failed={audit.isError} label={msg('Audit')}>
	<AdminAudit events={audit.data!.events} />
	{#if pageCount > 1}
		<Pagination
			page={filters().page}
			{pageCount}
			label={$t('Administration pages')}
			onPage={setPage}
		/>
	{/if}
</AdminSectionState>
