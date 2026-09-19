<script lang="ts">
	import { createMutation, createQuery } from '@tanstack/svelte-query';
	import type { components } from '$lib/api/schema';
	import { apiRequest } from '$lib/api/client';
	import { apiErrorMessage } from '$lib/api/errors';
	import AdminNotices from '$lib/features/admin/AdminNotices.svelte';
	import AdminSectionState from '$lib/features/admin/AdminSectionState.svelte';
	import AdminSettings from '$lib/features/admin/AdminSettings.svelte';
	import { getAdminFilters } from '$lib/features/admin/filters';
	import { adminMutationOptions } from '$lib/features/admin/mutations';
	import { adminSettingsQuery } from '$lib/features/admin/queries';
	import { msg, t, type MessageKey } from '$lib/i18n';

	type Settings = components['schemas']['AdminSettingsView'];

	let error = $state('');
	let notice = $state<MessageKey | null>(null);
	const { filters } = getAdminFilters();
	const settings = createQuery(() => adminSettingsQuery(filters(), true));
	const adminMutation = createMutation(() =>
		adminMutationOptions('settings', () => settings.refetch())
	);
	const busy = $derived(adminMutation.isPending);
	const settingFields: ReadonlyArray<readonly [keyof Settings, MessageKey]> = [
		['metadata_contact_email', msg('Metadata contact email')],
		['ncbi_api_key', msg('NCBI API key')],
		['openalex_api_key', msg('OpenAlex API key')],
		['nasa_ads_token', msg('NASA ADS token')],
		['ieee_api_key', msg('IEEE API key')],
		['session_days', msg('Session lifetime in days')],
		['max_pdf_bytes', msg('Maximum PDF size in bytes')],
		['max_attachment_bytes', msg('Maximum attachment size in bytes')],
		['export_ttl_hours', msg('Export lifetime in hours')]
	] as const;

	function saveSettings(event: SubmitEvent) {
		event.preventDefault();
		const form = event.currentTarget as HTMLFormElement;
		const values: Record<string, FormDataEntryValue | number> = Object.fromEntries(
			new FormData(form)
		);
		for (const key of ['session_days', 'max_pdf_bytes', 'max_attachment_bytes', 'export_ttl_hours'])
			values[key] = Number(values[key]);
		error = '';
		notice = null;
		void adminMutation
			.mutateAsync({
				run: () => apiRequest('PUT', '/admin/settings', { body: values as Settings })
			})
			.then(() => {
				notice = msg('Settings saved');
			})
			.catch((reason) => {
				error = apiErrorMessage(reason, $t('Administration action failed'));
			});
	}
</script>

<AdminNotices {error} {notice} />
<AdminSectionState loading={settings.isPending} failed={settings.isError} label={msg('Settings')}>
	<AdminSettings settings={settings.data!} fields={settingFields} {busy} onSave={saveSettings} />
</AdminSectionState>
