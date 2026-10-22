<script lang="ts">
	import { onMount } from 'svelte';
	import type { Snippet } from 'svelte';
	import { SvelteMap } from 'svelte/reactivity';
	import { Combobox, Portal, useListCollection } from '@skeletonlabs/skeleton-svelte';
	import Icon from '#lib/design/Icon.svelte';
	import { activeLocale, t } from '#lib/i18n.js';

	type Option = { value: string; label: string; group?: string; kind?: string };
	let {
		value = $bindable(''),
		search = $bindable<string | null>(null),
		open = $bindable(false),
		label,
		hideLabel = false,
		selectedLabel,
		selectedKind,
		options,
		placeholder = '',
		emptyLabel,
		emptyOption,
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
		selectedKind?: string;
		options: Option[];
		placeholder?: string;
		emptyLabel?: string;
		emptyOption?: Pick<Option, 'group' | 'kind'>;
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
	const selectionKindId = $props.id();
	onMount(() => {
		// Keep popups inside a modal's accessibility and focus boundary.
		portalTarget = input?.closest<HTMLElement>('[role="dialog"]') ?? undefined;
	});
	const selected = $derived(options.find((option: Option) => option.value === value));
	const selectedText = $derived(
		selectedLabel ?? selected?.label ?? (allowCustomValue ? value : '')
	);
	const selectionKind = $derived(
		value && selectedText && search === null ? (selectedKind ?? selected?.kind) : undefined
	);
	const items = $derived(
		emptyLabel && (filterOptions || !search)
			? [{ value: '', label: emptyLabel, ...emptyOption }, ...options]
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
	const groups = $derived.by(() => {
		const result = new SvelteMap<string | undefined, Option[]>();
		for (const option of matching) {
			const group = result.get(option.group);
			if (group) group.push(option);
			else result.set(option.group, [option]);
		}
		return [...result];
	});
</script>

<Combobox
	class={`min-w-0 ${className}`.trim()}
	{collection}
	{disabled}
	{allowCustomValue}
	{required}
	{open}
	inputValue={search ?? selectedText}
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
	{#if selectedKind || emptyOption?.kind || selected?.kind}
		<div class="flex min-w-0 items-center justify-between gap-2">
			<Combobox.Label class={hideLabel ? 'sr-only' : ''}>{label}</Combobox.Label>
			{#if selectionKind}
				<span
					id={selectionKindId}
					class="shrink-0 rounded-full bg-surface-100-900 px-2 text-xs leading-4 text-surface-600-400"
					>{selectionKind}</span
				>
			{/if}
		</div>
	{:else}
		<Combobox.Label class={hideLabel ? 'sr-only' : ''}>{label}</Combobox.Label>
	{/if}
	<Combobox.Control>
		<Combobox.Input placeholder={placeholder || emptyLabel} class="pr-10">
			{#snippet element(attributes)}<input
					{...attributes}
					aria-describedby={[
						attributes['aria-describedby'],
						selectionKind ? selectionKindId : undefined
					]
						.filter(Boolean)
						.join(' ') || undefined}
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
		<Combobox.Positioner class="max-w-[calc(100vw-2rem)] min-w-[var(--reference-width)]">
			<!-- Zag derives the positioner's stacking layer from its first child. -->
			<div
				hidden={!open}
				class="z-100 overflow-hidden rounded-container border border-surface-200-800 bg-surface-50-950 shadow-xl"
			>
				<Combobox.Content class="max-h-72 overflow-y-auto rounded-none border-0">
					{#each groups as [group, options] (group)}
						{#if group}
							<Combobox.ItemGroup class="border-t border-surface-200-800 first:border-0">
								<Combobox.ItemGroupLabel
									class="px-3 pt-3 pb-1 text-xs font-semibold text-surface-600-400"
								>
									{group}
								</Combobox.ItemGroupLabel>
								{#each options as option (option.value)}{@render choice(option)}{/each}
							</Combobox.ItemGroup>
						{:else}
							{#each options as option (option.value)}{@render choice(option)}{/each}
						{/if}
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

{#snippet choice(option: Option)}
	<Combobox.Item item={option}>
		<span class="flex min-w-0 flex-1 items-center justify-between gap-4">
			<Combobox.ItemText class="min-w-0 break-words">{option.label}</Combobox.ItemText>
			{#if option.kind}<span class="shrink-0 text-xs text-surface-600-400">{option.kind}</span>{/if}
		</span>
		<Combobox.ItemIndicator aria-hidden="true">✓</Combobox.ItemIndicator>
	</Combobox.Item>
{/snippet}
