<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import Pagination from '#lib/design/Pagination.svelte';
	import AdminOverview from '#lib/features/admin/AdminOverview.svelte';
	import AdminSectionState from '#lib/features/admin/AdminSectionState.svelte';
	import { getAdminFilters } from '#lib/features/admin/filters.js';
	import { adminOverviewQuery } from '#lib/features/admin/queries.js';
	import { msg, t } from '#lib/i18n.js';

	const { filters, setPage, setPageSize } = getAdminFilters();
	const overview = createQuery(() => adminOverviewQuery(filters(), true));
	const events = $derived(overview.data?.recent_events);
</script>

<AdminSectionState
	busy={overview.isFetching}
	onRetry={() => void overview.refetch()}
	loading={overview.isPending}
	failed={overview.isError}
	label={msg('Overview')}
>
	<AdminOverview overview={overview.data!} />
	<Pagination
		page={filters().page}
		pageSize={filters().pageSize}
		pageCount={Math.max(1, Math.ceil((events?.total ?? 0) / filters().pageSize))}
		total={events?.total ?? 0}
		busy={overview.isFetching}
		label={$t('Administration pages')}
		onPage={setPage}
		onPageSize={setPageSize}
	/>
</AdminSectionState>
