<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import AdminSectionState from '#lib/features/admin/AdminSectionState.svelte';
	import AdminWorkflows from '#lib/features/admin/AdminWorkflows.svelte';
	import { getAdminFilters } from '#lib/features/admin/filters.js';
	import { adminWorkflowsQuery } from '#lib/features/admin/queries.js';
	import { msg } from '#lib/i18n.js';

	const { filters } = getAdminFilters();
	const workflows = createQuery(() => adminWorkflowsQuery(filters(), true));
</script>

<AdminSectionState
	loading={workflows.isPending}
	failed={workflows.isError}
	label={msg('Workflows')}
>
	<AdminWorkflows workflows={workflows.data!.workflows} />
</AdminSectionState>
