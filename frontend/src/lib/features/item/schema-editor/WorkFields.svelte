<script lang="ts">
	import {
		getFormContext,
		getComponent,
		retrieveUiOption,
		retrieveTranslate,
		type ComponentProps
	} from '@sjsf/form';
	import { createObjectContext, setObjectContext } from '@sjsf/form/fields/object/context.svelte';
	import ObjectField from '@sjsf/form/fields/object/object-field.svelte';
	import { fieldTitle } from './labels.js';
	import { t, activeLocale } from '#lib/i18n.js';
	import AddField from './AddField.svelte';
	import { getFieldVisibility, hasFieldValue } from './field-visibility.svelte.js';
	import { fieldSummary } from './summary.js';
	import LazySection from './LazySection.svelte';
	let { config, value = $bindable(), translate }: ComponentProps['objectField'] = $props();
	const ctx = getFormContext();
	const visibility = getFieldVisibility();
	const obj = createObjectContext({
		ctx,
		config: () => config,
		value: () => value,
		setValue: (next) => (value = next),
		get translate() {
			return translate;
		}
	});
	setObjectContext(obj);
	const Property = $derived(getComponent(ctx, 'objectPropertyField', config));
	const primary = [
		'title',
		'type',
		'date_published',
		'description',
		'container',
		'contributors',
		'identifiers',
		'funding_references',
		'subjects'
	];
	function title(path: readonly (string | number)[], fallback: string) {
		void $activeLocale;
		return fieldTitle(path, fallback);
	}
	const fields = $derived(obj.propertiesOrder());
	let expanded = $state<Record<string, boolean>>({});
	let additionalExpanded = $state(false);
	const additionalReveal = $derived(
		Math.max(
			0,
			...fields
				.filter((name) => !primary.includes(name))
				.map((name) => visibility.expansion([name]))
		)
	);
</script>

{#if config.path.length}
	<ObjectField
		type="field"
		{config}
		bind:value
		uiOption={(opt) => retrieveUiOption(ctx, config, opt)}
		{translate}
	/>
{:else}
	<div class="min-w-0">
		<div
			class="grid min-w-0 grid-cols-[repeat(auto-fit,minmax(min(100%,max(18rem,calc(50%_-_0.625rem))),1fr))] items-start gap-5"
		>
			{#each primary.filter((name) => fields.includes(name)) as property (property)}
				{@const cfg = obj.propertyConfig(config, property, false)}
				{#if ['title', 'type', 'date_published', 'description'].includes(property)}
					<div
						class={!visibility.isVisible(cfg, value?.[property])
							? 'hidden'
							: ['title', 'description'].includes(property)
								? 'col-span-full min-w-0'
								: 'min-w-0'}
					>
						{@render field(property)}
					</div>
				{:else}
					{#if property === 'container'}<AddField {config} {value} />{/if}
					{@const preview = fieldSummary(value?.[property])}
					{@const count = Array.isArray(value?.[property]) ? value[property].length : undefined}
					<LazySection
						data-work-group={property}
						reveal={visibility.expansion(cfg.path)}
						class={`min-w-0 rounded-lg border border-surface-300-700 p-4 ${['container', 'contributors', 'subjects'].includes(property) ? 'col-span-full' : ''}`}
						bind:open={
							() =>
								expanded[property] ??
								(property === 'container' && hasFieldValue(value?.[property])),
							(next) => (expanded[property] = next)
						}
					>
						{#snippet summary()}<summary class="min-w-0 cursor-pointer font-medium">
								<span>{title(cfg.path, cfg.title)}</span>
								{#if count !== undefined}<span class="ml-2 text-sm font-normal text-surface-600-400"
										>({count})</span
									>{/if}
								{#if preview}<span
										class="mt-1 block truncate text-sm font-normal text-surface-600-400"
										title={preview}>{preview}</span
									>{/if}
							</summary>{/snippet}
						<div class="mt-4 min-w-0">{@render field(property)}</div>
					</LazySection>
				{/if}
			{/each}
			<LazySection
				bind:open={additionalExpanded}
				reveal={additionalReveal}
				class="col-span-full min-w-0 rounded-lg border border-surface-300-700 p-4"
			>
				{#snippet summary()}<summary class="cursor-pointer font-medium"
						>{$t('Additional metadata')}</summary
					>{/snippet}
				<div
					class="mt-4 grid min-w-0 grid-cols-[repeat(auto-fit,minmax(min(100%,max(11rem,calc((100%_-_2rem)/3))),1fr))] items-start gap-4"
				>
					{#each fields.filter((name) => !primary.includes(name)) as property (property)}{@render field(
							property
						)}{/each}
				</div>
			</LazySection>
		</div>
	</div>
{/if}

{#snippet field(property: string)}
	{@const cfg = obj.propertyConfig(config, property, false)}
	<Property
		type="field"
		{property}
		isAdditional={false}
		bind:value={() => value?.[property], (next) => obj.set(property, next)}
		config={cfg}
		uiOption={(opt) => retrieveUiOption(ctx, cfg, opt)}
		translate={retrieveTranslate(ctx, cfg)}
	/>
{/snippet}
