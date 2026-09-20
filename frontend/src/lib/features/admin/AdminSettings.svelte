<script lang="ts">
	import Panel from '$lib/design/Panel.svelte';
	import { t, type MessageKey } from '$lib/i18n';
	import type { components } from '$lib/api/schema';
	import Button from '$lib/design/Button.svelte';

	type Settings = components['schemas']['AdminSettingsView'];

	let { settings, fields, busy, onSave } = $props<{
		settings: Settings;
		fields: ReadonlyArray<readonly [keyof Settings, MessageKey]>;
		busy: boolean;
		onSave: (event: SubmitEvent) => void;
	}>();
</script>

<Panel class="grid grid-cols-1 gap-3">
	<h2>{$t('Runtime settings')}</h2>
	<form class="grid grid-cols-1 gap-3" onsubmit={onSave}>
		{#each fields as [key, label] (key)}
			<label
				>{$t(label)}<input
					class="input"
					name={key}
					type={typeof settings[key] === 'number' ? 'number' : 'text'}
					value={settings[key]}
					required={typeof settings[key] === 'number'}
				/></label
			>
		{/each}
		<p class="text-surface-600-400">
			{$t('Database: {url}', { url: settings.database_url })}<br />{$t('Data directory: {path}', {
				path: settings.data_dir
			})}
		</p>
		<Button variant="filled" disabled={busy}>{$t('Save settings')}</Button>
	</form>
</Panel>
