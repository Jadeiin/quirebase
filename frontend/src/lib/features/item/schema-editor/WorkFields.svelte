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
	let { config, value = $bindable(), translate }: ComponentProps['objectField'] = $props();
	const ctx = getFormContext();
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
	let expanded = $state<Record<string, boolean>>({ container: true });
	let additionalExpanded = $state(false);
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
	<div class="@container/work min-w-0">
		<div class="grid min-w-0 grid-cols-1 items-start gap-5 @min-[40rem]/work:grid-cols-2">
			{#each primary.filter((name) => fields.includes(name)) as property (property)}
				{#if ['title', 'type', 'date_published', 'description'].includes(property)}
					<div
						class={['title', 'description'].includes(property)
							? 'col-span-full min-w-0'
							: 'min-w-0'}
					>
						{@render field(property)}
					</div>
				{:else}
					{@const cfg = obj.propertyConfig(config, property, false)}
					<details
						data-work-group={property}
						class={`min-w-0 rounded-lg border border-surface-300-700 p-4 ${['container', 'contributors', 'subjects'].includes(property) ? 'col-span-full' : ''}`}
						bind:open={() => expanded[property] ?? false, (next) => (expanded[property] = next)}
					>
						<summary class="cursor-pointer font-medium">{title(cfg.path, cfg.title)}</summary>
						<div class="mt-4 min-w-0">{@render field(property)}</div>
					</details>
				{/if}
			{/each}
			<details
				bind:open={additionalExpanded}
				class="@container/schema col-span-full min-w-0 rounded-lg border border-surface-300-700 p-4"
			>
				<summary class="cursor-pointer font-medium">{$t('Additional metadata')}</summary>
				<div
					class="mt-4 grid min-w-0 grid-cols-1 items-start gap-4 @min-[24rem]/schema:grid-cols-2 @min-[48rem]/schema:grid-cols-3"
				>
					{#each fields.filter((name) => !primary.includes(name)) as property (property)}{@render field(
							property
						)}{/each}
				</div>
			</details>
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
