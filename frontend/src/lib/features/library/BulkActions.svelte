<script lang="ts">
	import { bibliographyFormats } from '#lib/export-preferences.js';
	import SearchSelect from '#lib/design/SearchSelect.svelte';
	import TagSelect from '#lib/features/tags/TagSelect.svelte';
	import { can } from '#lib/authorization/can.js';
	import type { LibraryProject } from '#lib/features/library/queries.js';
	import { t } from '#lib/i18n.js';
	import Button from '#lib/design/Button.svelte';
	import { canRunBulkAction } from '#lib/workspaces/actions.js';
	import { getWorkspaceContext } from '#lib/workspaces/context.svelte.js';

	let {
		element = $bindable(),
		selectedCount,
		bulkAction = $bindable(''),
		bulkProject = $bindable(''),
		bulkTag = $bindable(''),
		exportFormat = $bindable('bibtex'),
		projects = [],
		busy,
		onApply,
		onClearSelection
	}: {
		element?: HTMLElement;
		selectedCount: number;
		bulkAction: string;
		bulkProject: string;
		bulkTag: string;
		exportFormat: string;
		projects: LibraryProject[];
		busy: boolean;
		onApply: () => void;
		onClearSelection: () => void;
	} = $props();
	const workspace = getWorkspaceContext();
	const assignableProjects: LibraryProject[] = $derived(
		projects.filter((project: LibraryProject) => can(project.authorization, 'project_item.manage'))
	);
	const needsConfiguration = $derived(
		['add_project', 'add_tag', 'bibliography'].includes(bulkAction)
	);
	const validationMessage = $derived(
		!bulkAction
			? $t('Choose an action to continue.')
			: !canRunBulkAction(workspace.can, bulkAction as import('./mutations.js').LibraryBulkAction)
				? $t('This action is no longer available.')
				: bulkAction === 'add_project' && !bulkProject
					? $t('Choose a Project to continue.')
					: bulkAction === 'add_tag' && !bulkTag.trim()
						? $t('Choose or enter a Tag to continue.')
						: ''
	);
	$effect(() => {
		if (bulkProject && !assignableProjects.some((project) => project.id === bulkProject)) {
			bulkProject = '';
		}
	});
</script>

{#if selectedCount}
	<section
		bind:this={element}
		data-library-bulk-actions
		aria-label={$t('Bulk actions')}
		aria-busy={busy}
		class="sticky top-20 z-30 mt-4 grid grid-cols-1 gap-3 rounded-xl border border-primary-700-300/30 bg-surface-50-950 p-3 shadow-lg lg:top-3 lg:flex lg:flex-wrap lg:items-center"
	>
		<div class="flex items-center justify-between gap-3 lg:contents">
			<div class="min-w-0 lg:mr-auto">
				<strong aria-live="polite">{$t('{count} selected', { count: selectedCount })}</strong>
				<p class="m-0 text-xs text-surface-600-400">{$t('Current page only')}</p>
			</div>
			<Button class="shrink-0 lg:order-2" size="sm" onclick={onClearSelection}
				>{$t('Clear selection')}</Button
			>
		</div>
		<div
			class="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-2 sm:flex sm:flex-wrap lg:order-1"
		>
			<select
				class="select h-8 w-full min-w-0 sm:w-auto sm:min-w-36"
				class:col-span-2={needsConfiguration}
				bind:value={bulkAction}
				aria-label={$t('Bulk action')}
				disabled={busy}
			>
				<option value="">{$t('Choose action')}</option>
				{#if canRunBulkAction(workspace.can, 'add_project')}<option value="add_project"
						>{$t('Add to Project')}</option
					>{/if}
				{#if canRunBulkAction(workspace.can, 'add_tag')}<option value="add_tag"
						>{$t('Add Tag')}</option
					>{/if}
				{#if canRunBulkAction(workspace.can, 'bibliography')}<option value="bibliography"
						>{$t('Export bibliography')}</option
					>{/if}
				{#if canRunBulkAction(workspace.can, 'documents')}<option value="documents"
						>{$t('Download documents')}</option
					>{/if}
				{#if canRunBulkAction(workspace.can, 'delete')}<option value="delete"
						>{$t('Permanently delete')}</option
					>{/if}
			</select>
			{#if bulkAction === 'add_project'}
				<SearchSelect
					class="w-full min-w-0 sm:w-56"
					label={$t('Select Project')}
					hideLabel
					emptyLabel={$t('Select Project')}
					bind:value={bulkProject}
					disabled={busy}
					options={assignableProjects.map((project: LibraryProject) => ({
						value: project.id,
						label: project.name
					}))}
				/>
			{/if}
			{#if bulkAction === 'add_tag'}<TagSelect
					class="w-full min-w-0 sm:w-56"
					label={$t('Select Tag')}
					emptyLabel={$t('Select Tag')}
					hideLabel
					valueBy="name"
					allowCustomValue
					disabled={busy}
					bind:value={bulkTag}
				/>{/if}
			{#if bulkAction === 'bibliography'}<select
					class="select h-8 w-full min-w-0 sm:w-auto sm:min-w-36"
					aria-label={$t('Format')}
					disabled={busy}
					bind:value={exportFormat}
				>
					{#each bibliographyFormats as choice (choice.value)}
						<option value={choice.value}>{$t(choice.label)}</option>
					{/each}
				</select>{/if}
			<Button
				variant="filled"
				disabled={busy || Boolean(validationMessage)}
				aria-describedby={busy || validationMessage ? 'library-bulk-hint' : undefined}
				onclick={onApply}>{$t('Apply')}</Button
			>
		</div>
		{#if busy || validationMessage}
			<p id="library-bulk-hint" class="m-0 text-xs text-surface-600-400 lg:order-3 lg:basis-full">
				{busy ? $t('Applying to the selected Items…') : validationMessage}
			</p>
		{/if}
	</section>
{/if}
