<script lang="ts">
	import { getFormContext, getIdByPath, type Config } from '@sjsf/form';
	import type { SchemaObjectValue } from '@sjsf/form/core';
	import { getObjectContext } from '@sjsf/form/fields/object/context.svelte';
	import { tick } from 'svelte';
	import { t, activeLocale } from '#lib/i18n.js';
	import { getFieldVisibility } from './field-visibility.svelte.js';
	import { fieldTitle } from './labels.js';

	let { config, value }: { config: Config; value?: SchemaObjectValue | null } = $props();
	const object = getObjectContext();
	const form = getFormContext();
	const visibility = getFieldVisibility();
	const label = $derived.by(() => {
		void $activeLocale;
		return config.path.length ? fieldTitle(config.path, config.title) : $t('Metadata');
	});
	const available = $derived(
		object
			.propertiesOrder()
			.map((property) => ({
				property,
				config: object.propertyConfig(config, property, object.isAdditionalProperty(property))
			}))
			// Contributor entities are activated through the existing type selector.
			.filter(
				(field) =>
					!['person', 'organization'].includes(field.property) &&
					!visibility.isVisible(field.config, value?.[field.property])
			)
	);
	const options = $derived.by(() => {
		void $activeLocale;
		return available.map((field) => ({
			...field,
			title: fieldTitle(field.config.path, field.config.title)
		}));
	});
	async function add(event: Event) {
		const select = event.currentTarget as HTMLSelectElement;
		const elementForm = select.closest('form');
		const property = select.value;
		if (!property) return;
		const path = [...config.path, property];
		visibility.reveal(path);
		select.value = '';
		await tick();
		const element = elementForm?.querySelector<HTMLElement>(
			`[data-metadata-field="${CSS.escape(JSON.stringify(path))}"]`
		);
		if (!element) return;
		let ancestor: HTMLElement | null = element;
		while (ancestor) {
			if (ancestor instanceof HTMLDetailsElement) ancestor.open = true;
			ancestor = ancestor.parentElement;
		}
		const details = element.querySelector('details');
		if (details) details.open = true;
		const target = element.querySelector<HTMLElement>(`[id="${getIdByPath(form, path)}"]`);
		(target?.matches('input, select, textarea')
			? target
			: element.querySelector<HTMLElement>('input, select, textarea, button')
		)?.focus();
	}
</script>

{#if available.length}
	<div class="col-span-full">
		<select
			class="select h-8 w-auto max-w-full"
			aria-label={$t('Add field to {label}', { label })}
			onchange={add}
		>
			<option value="">{$t('Add field')}</option>
			{#each options as field (field.property)}
				<option value={field.property}>{field.title}</option>
			{/each}
		</select>
	</div>
{/if}
