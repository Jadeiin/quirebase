<script lang="ts">
	import { createMutation, createQuery } from '@tanstack/svelte-query';
	import { apiRequest } from '#lib/api/client.js';
	import { apiErrorMessage } from '#lib/api/errors.js';
	import AdminMaintenance from '#lib/features/admin/AdminMaintenance.svelte';
	import AdminNotices from '#lib/features/admin/AdminNotices.svelte';
	import AdminSectionState from '#lib/features/admin/AdminSectionState.svelte';
	import { getAdminFilters } from '#lib/features/admin/filters.js';
	import { adminMutationOptions } from '#lib/features/admin/mutations.js';
	import { adminMaintenanceQuery } from '#lib/features/admin/queries.js';
	import { getWorkflowCenter } from '#lib/features/workflows/center.svelte.js';
	import { msg, t, type MessageKey } from '#lib/i18n.js';

	let error = $state('');
	let notice = $state<MessageKey | null>(null);
	const { filters } = getAdminFilters();
	const workflowCenter = getWorkflowCenter();
	const maintenance = createQuery(() => adminMaintenanceQuery(filters(), true));
	const adminMutation = createMutation(() =>
		adminMutationOptions('maintenance', () => maintenance.refetch())
	);
	const busy = $derived(adminMutation.isPending);
	const maintenanceOperations = [['check_objects', msg('Check stored objects')]] as const;

	function runMaintenance(operation: (typeof maintenanceOperations)[number][0]) {
		error = '';
		notice = msg('Maintenance operation started');
		void adminMutation
			.mutateAsync({
				run: async () => {
					const started = await apiRequest('POST', '/admin/maintenance/{operation}', {
						params: { path: { operation } }
					});
					await workflowCenter.track(started.id, {
						label: $t('Maintenance: {operation}', {
							operation: $t(
								maintenanceOperations.find(([key]) => key === operation)?.[1] ?? operation
							)
						}),
						successMessage: msg('Maintenance operation completed'),
						failureMessage: msg('Maintenance operation failed')
					}).settled;
				}
			})
			.then(() => {
				notice = msg('Maintenance operation completed');
			})
			.catch((reason) => {
				error = apiErrorMessage(reason, $t('Maintenance operation failed'));
			});
	}
</script>

<AdminNotices {error} {notice} />
<AdminSectionState
	loading={maintenance.isPending}
	failed={maintenance.isError}
	label={msg('Maintenance')}
>
	<AdminMaintenance
		maintenance={maintenance.data!}
		operations={maintenanceOperations}
		{busy}
		onRun={runMaintenance}
	/>
</AdminSectionState>
