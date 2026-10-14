<script lang="ts">
	import { getFormContext, selectAttributes, type ComponentProps } from '@sjsf/form';
	import { multipleOptions, idMapper } from '@sjsf/form/options.svelte';
	let {
		value = $bindable(),
		config,
		handlers,
		options,
		mapped = multipleOptions({
			mapper: () => idMapper(options),
			value: () => value,
			update: (next) => (value = next)
		})
	}: ComponentProps['checkboxesWidget'] = $props();
	const ctx = getFormContext();
</script>

<select
	class="select"
	multiple
	aria-label={config.title}
	{...selectAttributes(ctx, config, 'select', handlers, {})}
	bind:value={mapped.current}
>
	{#each options as option (option.id)}<option
			value={option.mappedValue ?? option.id}
			disabled={option.disabled}>{option.label}</option
		>{/each}
</select>
