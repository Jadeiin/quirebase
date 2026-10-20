<script lang="ts">
	import { onMount } from 'svelte';
	import type { Snippet } from 'svelte';
	import { Combobox, Portal, useListCollection } from '@skeletonlabs/skeleton-svelte';
	import Icon from '#lib/design/Icon.svelte';
	import { activeLocale, t } from '#lib/i18n.js';

	type Option = { value: string; label: string };
	let {
		value = $bindable(''),
		search = $bindable<string | null>(null),
		open = $bindable(false),
		label,
		hideLabel = false,
		selectedLabel,
		options,
		placeholder = '',
		emptyLabel,
		disabled = false,
		filterOptions = true,
		loading = false,
		allowCustomValue = false,
		inputName,
		inputType = 'text',
		required = false,
		footer,
		class: className = ''
	}: {
		value?: string;
		search?: string | null;
		open?: boolean;
		label: string;
		hideLabel?: boolean;
		selectedLabel?: string;
		options: Option[];
		placeholder?: string;
		emptyLabel?: string;
		disabled?: boolean;
		filterOptions?: boolean;
		loading?: boolean;
		allowCustomValue?: boolean;
		inputName?: string;
		inputType?: 'text' | 'url';
		required?: boolean;
		footer?: Snippet;
		class?: string;
	} = $props();

	let input = $state<HTMLInputElement>();
	let footerElement = $state<HTMLDivElement>();
	let portalTarget = $state<HTMLElement>();
	onMount(() => {
		// Keep popups inside a modal's accessibility and focus boundary.
		portalTarget = input?.closest<HTMLElement>('[role="dialog"]') ?? undefined;
	});
	const selected = $derived(options.find((option: Option) => option.value === value));
	const items = $derived(
		emptyLabel && (filterOptions || !search)
			? [{ value: '', label: emptyLabel }, ...options]
			: options
	);
	const query = $derived(search?.toLocaleLowerCase($activeLocale) ?? '');
	const matching = $derived(
		query && filterOptions
			? items.filter((option: Option) =>
					option.label.toLocaleLowerCase($activeLocale).includes(query)
				)
			: items
	);
	const collection = $derived(
		useListCollection({
			items: matching,
			itemToValue: (option) => option.value,
			itemToString: (option) => option.label
		})
	);
</script>

<Combobox
	class={`min-w-0 ${className}`.trim()}
	{collection}
	{disabled}
	{allowCustomValue}
	{required}
	{open}
	inputValue={search ?? selectedLabel ?? selected?.label ?? (allowCustomValue ? value : '')}
	value={value ? [value] : []}
	positioning={{ strategy: 'fixed' }}
	openOnClick
	onInteractOutside={(event) => {
		const target = event.detail.target;
		if (target instanceof Node && footerElement?.contains(target)) event.preventDefault();
	}}
	onInputValueChange={(details) => {
		if (details.reason === 'input-change') {
			search = details.inputValue;
			if (allowCustomValue) value = details.inputValue;
		}
	}}
	onValueChange={(details) => {
		value = details.value[0] ?? '';
		search = null;
	}}
	onOpenChange={(details) => {
		open = details.open;
		if (!details.open || details.reason === 'trigger-click') search = null;
	}}
>
	<Combobox.Label class={hideLabel ? 'sr-only' : ''}>{label}</Combobox.Label>
	<Combobox.Control>
		<Combobox.Input placeholder={placeholder || emptyLabel} class="pr-10">
			{#snippet element(attributes)}<input
					{...attributes}
					name={inputName}
					type={inputType}
					{required}
					bind:this={input}
				/>{/snippet}
		</Combobox.Input>
		<Combobox.Trigger aria-label={$t('Show options for {label}', { label })}
			><Icon name="chevron-down" size={16} /></Combobox.Trigger
		>
	</Combobox.Control>
	<Portal target={portalTarget}>
		<Combobox.Positioner class="min-w-[var(--reference-width)]">
			<!-- Zag derives the positioner's stacking layer from its first child. -->
			<div
				hidden={!open}
				class="z-100 overflow-hidden rounded-container border border-surface-200-800 bg-surface-50-950 shadow-xl"
			>
				<Combobox.Content class="max-h-72 overflow-y-auto rounded-none border-0">
					{#each matching as option (option.value)}
						<Combobox.Item item={option}>
							<Combobox.ItemText>{option.label}</Combobox.ItemText>
							<Combobox.ItemIndicator aria-hidden="true">✓</Combobox.ItemIndicator>
						</Combobox.Item>
					{:else}
						{#if !loading}<p class="px-2 py-1 text-sm text-surface-600-400">
								{$t('No matching options.')}
							</p>{/if}
					{/each}
				</Combobox.Content>
				{#if footer}<div bind:this={footerElement} class="px-2 pb-2">{@render footer()}</div>{/if}
			</div>
		</Combobox.Positioner>
	</Portal>
</Combobox>
