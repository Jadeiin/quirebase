<script lang="ts">
	import type { HTMLInputAttributes } from 'svelte/elements';
	import DateField from '#lib/design/DateField.svelte';
	import { t } from '#lib/i18n.js';
	let { value = $bindable(''), inputAttributes = {} } = $props<{
		value?: string;
		inputAttributes?: HTMLInputAttributes;
	}>();
	type Precision = 'year' | 'month' | 'day';
	let precision = $state<Precision>(
		value.length >= 10 ? 'day' : value.length === 7 ? 'month' : 'year'
	);
	function changePrecision(event: Event) {
		const next = (event.currentTarget as HTMLSelectElement).value as Precision;
		const length = next === 'day' ? 10 : next === 'month' ? 7 : 4;
		value = value.length >= length ? value.slice(0, length) : '';
		precision = next;
	}
</script>

{#if value.includes('T')}
	<label>{$t('Publication date')}<input class="input" {...inputAttributes} bind:value /></label>
{:else}
	<div class="grid grid-cols-[auto_minmax(0,1fr)] items-start gap-2">
		<label
			>{$t('Date precision')}<select class="select" value={precision} onchange={changePrecision}>
				<option value="year">{$t('Year')}</option>
				<option value="month">{$t('Year and month')}</option>
				<option value="day">{$t('Full date')}</option>
			</select></label
		>
		<DateField bind:value {precision} {inputAttributes} label={$t('Publication date')} />
	</div>
{/if}
