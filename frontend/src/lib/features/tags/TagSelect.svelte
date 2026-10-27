<script lang="ts">
	import { createInfiniteQuery, createQuery } from '@tanstack/svelte-query';
	import { can } from '#lib/authorization/can.js';
	import Button from '#lib/design/Button.svelte';
	import SearchSelect from '#lib/design/SearchSelect.svelte';
	import { apiErrorMessage } from '#lib/api/errors.js';
	import { activeLocale } from '#lib/locale.js';
	import { t } from 'lingui-for-svelte/macro';
	import { getWorkspaceContext } from '#lib/workspaces/context.svelte.js';
	import { tagOptionsQuery, tagsQuery } from './queries.js';

	let {
		value = $bindable(''),
		label,
		hideLabel = false,
		emptyLabel,
		disabled = false,
		manageOnly = false,
		valueBy = 'id',
		allowCustomValue = false,
		presetOptions = [],
		class: className = ''
	}: {
		value?: string;
		label: string;
		hideLabel?: boolean;
		emptyLabel: string;
		disabled?: boolean;
		manageOnly?: boolean;
		valueBy?: 'id' | 'name';
		allowCustomValue?: boolean;
		presetOptions?: { value: string; label: string }[];
		class?: string;
	} = $props();

	const { workspaceId } = getWorkspaceContext();
	let open = $state(false);
	let search = $state<string | null>(null);
	let submittedSearch = $state('');
	const selectedPreset = $derived(presetOptions.find((option) => option.value === value));
	const matchingPresets = $derived(
		presetOptions
			.filter((option) =>
				option.label
					.toLocaleLowerCase($activeLocale)
					.includes((search?.trim() ?? '').toLocaleLowerCase($activeLocale))
			)
			.map((option) => ({ ...option, group: $t`Filter conditions`, kind: $t`Condition` }))
	);
	$effect(() => {
		const query = search?.trim() ?? '';
		if (query === submittedSearch) return;
		const timeout = setTimeout(() => (submittedSearch = query), 200);
		return () => clearTimeout(timeout);
	});
	const tags = createInfiniteQuery(() => ({
		...tagOptionsQuery(workspaceId, submittedSearch),
		enabled: open
	}));
	const selection = createQuery(() => ({
		...tagsQuery(workspaceId, '', 0, 1, value),
		enabled: valueBy === 'id' && Boolean(value) && !selectedPreset
	}));
	const selectedLabel = $derived(
		selectedPreset?.label ??
			(valueBy === 'name'
				? value
				: (selection.data?.items[0]?.name ?? tags.data?.find((tag) => tag.id === value)?.name))
	);
	const options = $derived([
		...matchingPresets,
		...((search?.trim() ?? '') === submittedSearch ? (tags.data ?? []) : [])
			.filter((tag) => !manageOnly || can(tag.authorization, 'tag.manage'))
			.map((tag) => ({
				value: valueBy === 'name' ? tag.name : tag.id,
				label: tag.name,
				...(presetOptions.length ? { group: $t`Tags`, kind: $t`Tag` } : {})
			}))
			.filter((option) => !presetOptions.some((preset) => preset.value === option.value))
	]);
</script>

<SearchSelect
	bind:value
	bind:search
	bind:open
	{label}
	{hideLabel}
	class={className}
	{selectedLabel}
	selectedKind={presetOptions.length ? (selectedPreset ? $t`Condition` : $t`Tag`) : undefined}
	{emptyLabel}
	emptyOption={presetOptions.length
		? { group: $t`Filter conditions`, kind: $t`Condition` }
		: undefined}
	{disabled}
	{allowCustomValue}
	{options}
	filterOptions={false}
	loading={tags.isFetching || (search?.trim() ?? '') !== submittedSearch}
>
	{#snippet footer()}
		{#if tags.isError}
			<p role="alert" class="px-2 py-1 text-sm text-error-700-300">
				{apiErrorMessage(tags.error, $t`Unable to load Tags`)}
			</p>
		{:else if tags.isFetching}
			<p role="status" class="px-2 py-1 text-sm text-surface-600-400">{$t`Loading Tags…`}</p>
		{/if}
		{#if tags.hasNextPage}
			<Button
				class="w-full"
				disabled={tags.isFetchingNextPage}
				onclick={() => void tags.fetchNextPage()}
			>
				{$t`Load more Tags`}
			</Button>
		{/if}
	{/snippet}
</SearchSelect>
