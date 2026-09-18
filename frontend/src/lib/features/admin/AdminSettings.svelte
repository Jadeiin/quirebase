<script lang="ts">
	import { t, type MessageKey } from '$lib/i18n';
	import type { components } from '$lib/api/schema';

	type Settings = components['schemas']['AdminSettingsView'];

	let { settings, fields, busy, onSave } = $props<{
		settings: Settings;
		fields: ReadonlyArray<readonly [keyof Settings, MessageKey]>;
		busy: boolean;
		onSave: (event: SubmitEvent) => void;
	}>();
</script>

<section class="stack card border border-surface-300-700 bg-surface-50-950 p-5 shadow-sm">
	<h2>{$t('Runtime settings')}</h2>
	<form class="stack" onsubmit={onSave}>
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
			Database: {settings.database_url}<br />Data directory: {settings.data_dir}
		</p>
		<button class="btn preset-filled-primary-700-300 font-semibold" disabled={busy}
			>{$t('Save settings')}</button
		>
	</form>
</section>
