<script lang="ts">
	import Button from '#lib/design/Button.svelte';
	import { t } from '#lib/i18n.js';
	import type { IdentifierRow } from './metadata-draft.js';
	let { rows = $bindable(), rowKey } = $props<{
		rows: IdentifierRow[];
		rowKey: () => number;
	}>();
</script>

<div class="grid grid-cols-1 gap-2">
	{#each rows as row (row.key)}
		<div class="grid grid-cols-1 gap-2 sm:grid-cols-[1fr_2fr_auto] sm:items-end">
			<label>{$t('Provider')}<input class="input" bind:value={row.provider} /></label>
			<label>{$t('Identifier')}<input class="input" bind:value={row.value} /></label>
			<Button type="button" onclick={() => rows.splice(rows.indexOf(row), 1)}>{$t('Remove')}</Button
			>
		</div>
	{/each}
	<div>
		<Button type="button" onclick={() => rows.push({ key: rowKey(), provider: '', value: '' })}
			>{$t('Add identifier')}</Button
		>
	</div>
</div>
