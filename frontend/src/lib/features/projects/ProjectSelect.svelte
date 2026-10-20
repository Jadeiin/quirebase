<script lang="ts">
	import { createInfiniteQuery, createQuery } from '@tanstack/svelte-query';
	import { ApiError } from '#lib/api/client.js';
	import { apiErrorMessage } from '#lib/api/errors.js';
	import { can } from '#lib/authorization/can.js';
	import Button from '#lib/design/Button.svelte';
	import Notice from '#lib/design/Notice.svelte';
	import SearchSelect from '#lib/design/SearchSelect.svelte';
	import { t } from '#lib/i18n.js';
	import { getWorkspaceContext } from '#lib/workspaces/context.svelte.js';
	import { projectDetailQuery, projectOptionsQuery, type ProjectSummary } from './queries.js';

	let {
		value = $bindable(''),
		selectedProject = $bindable<ProjectSummary | null>(null),
		label,
		hideLabel = false,
		emptyLabel,
		disabled = false,
		manageOnly = false,
		class: className = ''
	}: {
		value?: string;
		selectedProject?: ProjectSummary | null;
		label: string;
		hideLabel?: boolean;
		emptyLabel: string;
		disabled?: boolean;
		manageOnly?: boolean;
		class?: string;
	} = $props();

	const { workspaceId } = getWorkspaceContext();
	let open = $state(false);
	let search = $state<string | null>(null);
	let submittedSearch = $state('');
	$effect(() => {
		const query = search?.trim() ?? '';
		if (query === submittedSearch) return;
		const timeout = setTimeout(() => (submittedSearch = query), 200);
		return () => clearTimeout(timeout);
	});
	const projects = createInfiniteQuery(() => ({
		...projectOptionsQuery(workspaceId, submittedSearch),
		enabled: open && !disabled
	}));
	const selection = createQuery(() => ({
		...projectDetailQuery(workspaceId, value),
		enabled: Boolean(value)
	}));
	function isUnavailable(reason: unknown) {
		return reason instanceof ApiError && [401, 403, 404].includes(reason.status);
	}
	const selectedDetail = $derived(selection.data?.id === value ? selection.data : undefined);
	const selectionFailed = $derived(selection.isError);
	const deniedOptions = $derived(projects.isError && isUnavailable(projects.error));
	$effect(() => {
		// A retained snapshot cannot authorize a target while its refresh is pending or failed.
		selectedProject =
			selection.isSuccess &&
			selection.fetchStatus === 'idle' &&
			selectedDetail &&
			(!manageOnly || can(selectedDetail.authorization, 'project_item.manage'))
				? selectedDetail
				: null;
	});
	const selectedLabel = $derived(
		selectionFailed
			? undefined
			: ((selectedProject?.id === value ? selectedProject.name : selectedDetail?.name) ??
					projects.data?.find((project) => project.id === value)?.name)
	);
	const options = $derived.by(() => {
		if ((search?.trim() ?? '') !== submittedSearch || deniedOptions) return [];
		const available = new Map((projects.data ?? []).map((project) => [project.id, project]));
		// Keep an existing selection visible even when it lies beyond the loaded pages.
		const choices =
			!submittedSearch && selectedDetail && !selectionFailed
				? new Map<string, ProjectSummary>([
						[selectedDetail.id, selectedDetail],
						...[...available].filter(([id]) => id !== selectedDetail.id)
					])
				: available;
		return [...choices.values()]
			.filter(
				(project) =>
					(!manageOnly || can(project.authorization, 'project_item.manage')) &&
					!(project.id === value && selectionFailed)
			)
			.map((project) => ({ value: project.id, label: project.name }));
	});
	const selectionError = $derived(
		value && selection.isError
			? apiErrorMessage(selection.error, $t('Unable to load Project.'))
			: value && selection.fetchStatus === 'paused'
				? $t('Unable to load Project.')
				: value &&
					  manageOnly &&
					  selectedDetail &&
					  !can(selectedDetail.authorization, 'project_item.manage')
					? $t('This action is no longer available.')
					: ''
	);
</script>

<div class={`min-w-0 ${className}`.trim()}>
	<SearchSelect
		bind:value
		bind:search
		bind:open
		{label}
		{hideLabel}
		{selectedLabel}
		{emptyLabel}
		{disabled}
		{options}
		filterOptions={false}
		loading={projects.isPending ||
			projects.isFetching ||
			projects.isError ||
			(search?.trim() ?? '') !== submittedSearch}
	>
		{#snippet footer()}
			{#if projects.isError || projects.fetchStatus === 'paused'}
				<p role="alert" class="px-2 py-1 text-sm text-error-700-300">
					{projects.isError
						? apiErrorMessage(projects.error, $t('Unable to load Projects.'))
						: $t('Unable to load Projects.')}
				</p>
				<Button
					type="button"
					class="w-full"
					disabled={projects.isFetching}
					onclick={() => void projects.refetch()}>{$t('Retry')}</Button
				>
			{:else if projects.isFetching}
				<p role="status" class="px-2 py-1 text-sm text-surface-600-400">
					{$t('Loading Projects…')}
				</p>
			{/if}
			{#if projects.hasNextPage && !deniedOptions}
				<Button
					type="button"
					class="w-full"
					disabled={projects.fetchStatus !== 'idle'}
					onclick={() => void projects.fetchNextPage()}>{$t('Load more Projects')}</Button
				>
			{/if}
		{/snippet}
	</SearchSelect>
	{#if selectionError}
		<Notice as="div" variant="error" class="mt-2 flex flex-wrap items-center justify-between gap-2">
			<span>{selectionError}</span>
			<Button type="button" disabled={selection.isFetching} onclick={() => void selection.refetch()}
				>{$t('Retry')}</Button
			>
		</Notice>
	{/if}
</div>
