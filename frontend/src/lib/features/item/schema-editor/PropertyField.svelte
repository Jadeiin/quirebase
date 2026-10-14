<script lang="ts">
	import { getFormContext, retrieveUiOption, type ComponentProps } from '@sjsf/form';
	import ObjectProperty from '@sjsf/form/fields/object/object-property-field.svelte';
	import { activeLocale } from '#lib/i18n.js';
	import { fieldTitle } from './labels.js';
	let {
		value = $bindable(),
		config,
		uiOption,
		...props
	}: ComponentProps['objectPropertyField'] = $props();
	const ctx = getFormContext();
	const presentation = $derived.by(() => {
		void $activeLocale;
		return {
			...config,
			title: fieldTitle(config.path, config.title),
			uiSchema: collapsible
				? {
						...config.uiSchema,
						'ui:options': { ...config.uiSchema['ui:options'], hideTitle: true }
					}
				: config.uiSchema
		};
	});
	const collapsible = $derived(
		['object', 'array'].includes(String(config.schema.type)) &&
			!['person', 'organization'].includes(String(config.path.at(-1))) &&
			(config.path.length > 1 ||
				!['container', 'contributors', 'identifiers', 'funding_references', 'subjects'].includes(
					String(config.path[0])
				))
	);
	let expanded = $state(false);
	const entryCount = $derived(Array.isArray(value) ? value.length : undefined);
</script>

{#if collapsible}
	<details
		bind:open={expanded}
		class="col-span-full min-w-0 rounded-lg border border-surface-300-700 p-3"
	>
		<summary class="cursor-pointer font-medium">
			{presentation.title}{#if entryCount !== undefined}<span
					class="ml-2 text-sm text-surface-600-400">({entryCount})</span
				>{/if}
		</summary>
		<div class="mt-3 min-w-0">
			<ObjectProperty
				{...props}
				config={presentation}
				bind:value
				uiOption={(opt) => retrieveUiOption(ctx, presentation, opt)}
			/>
		</div>
	</details>
{:else}
	<ObjectProperty {...props} {uiOption} config={presentation} bind:value />
{/if}
