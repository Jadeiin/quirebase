<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import AdminOverview from '$lib/features/admin/AdminOverview.svelte';
	import AdminSectionState from '$lib/features/admin/AdminSectionState.svelte';
	import { getAdminFilters } from '$lib/features/admin/filters';
	import { adminOverviewQuery } from '$lib/features/admin/queries';
	import { msg } from '$lib/i18n';

	const { filters } = getAdminFilters();
	const overview = createQuery(() => adminOverviewQuery(filters(), true));
</script>

<AdminSectionState loading={overview.isPending} failed={overview.isError} label={msg('Overview')}>
	<AdminOverview overview={overview.data!} />
</AdminSectionState>
