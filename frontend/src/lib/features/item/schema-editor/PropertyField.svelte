<script lang="ts">
	import { getFormContext, retrieveUiOption, type ComponentProps } from '@sjsf/form';
	import ObjectProperty from '@sjsf/form/fields/object/object-property-field.svelte';
	import { activeLocale } from '#lib/i18n.js';
	import { fieldTitle } from './labels.js';
	import { getFieldVisibility } from './field-visibility.svelte.js';
	import { fieldSummary } from './summary.js';
	import LazySection from './LazySection.svelte';
	let { value = $bindable(), config, ...props }: ComponentProps['objectPropertyField'] = $props();
	const ctx = getFormContext();
	const visibility = getFieldVisibility();
	const visible = $derived(visibility.isVisible(config, value));
	$effect(() => visibility.remember(config.path, value));
	const entity = $derived(['person', 'organization'].includes(String(config.path.at(-1))));
	const presentation = $derived.by(() => {
		void $activeLocale;
		return {
			...config,
			title: fieldTitle(config.path, config.title),
			uiSchema:
				collapsible || entity
					? {
							...config.uiSchema,
							'ui:options': { ...config.uiSchema['ui:options'], hideTitle: true }
						}
					: config.uiSchema
		};
	});
	const collapsible = $derived(
		['object', 'array'].includes(String(config.schema.type)) &&
			(!entity || !config.required) &&
			(config.path.length > 1 ||
				!['container', 'contributors', 'identifiers', 'funding_references', 'subjects'].includes(
					String(config.path[0])
				))
	);
	let expanded = $state(false);
	const entryCount = $derived(Array.isArray(value) ? value.length : undefined);
	const preview = $derived.by(() => {
		void $activeLocale;
		return fieldSummary(value, String(config.path.at(-1)));
	});
</script>

{#if visible}
	<div class="contents" data-metadata-field={JSON.stringify(config.path)}>
		{#if collapsible}
			<LazySection
				bind:open={expanded}
				reveal={visibility.expansion(config.path)}
				class="col-span-full min-w-0 border-l-2 border-surface-300-700 pl-3"
			>
				{#snippet summary()}<summary class="cursor-pointer font-medium">
						{presentation.title}{#if entryCount !== undefined}<span
								class="ml-2 text-sm text-surface-600-400">({entryCount})</span
							>{/if}
						{#if preview}<span
								class="mt-1 block truncate text-sm font-normal text-surface-600-400"
								title={preview}>{preview}</span
							>{/if}
					</summary>{/snippet}
				<div class="mt-3 min-w-0">
					<ObjectProperty
						{...props}
						config={presentation}
						bind:value
						uiOption={(opt) => retrieveUiOption(ctx, presentation, opt)}
					/>
				</div>
			</LazySection>
		{:else}
			<ObjectProperty
				{...props}
				uiOption={(opt) => retrieveUiOption(ctx, presentation, opt)}
				config={presentation}
				bind:value
			/>
		{/if}
	</div>
{/if}
