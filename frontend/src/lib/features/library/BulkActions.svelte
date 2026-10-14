<script lang="ts">
	import { bibliographyFormats } from '#lib/export-preferences.js';
	import SearchSelect from '#lib/design/SearchSelect.svelte';
	import { can } from '#lib/authorization/can.js';
	import type { LibraryProject } from '#lib/features/library/queries.js';
	import { t } from '#lib/i18n.js';
	import Button from '#lib/design/Button.svelte';
	import { canRunBulkAction } from '#lib/workspaces/actions.js';
	import { getWorkspaceContext } from '#lib/workspaces/context.svelte.js';

	let {
		selectedCount,
		bulkAction = $bindable(''),
		bulkProject = $bindable(''),
		bulkTag = $bindable(''),
		exportFormat = $bindable('bibtex'),
		projects = [],
		busy,
		onApply,
		onClearSelection
	} = $props<{
		selectedCount: number;
		bulkAction: string;
		bulkProject: string;
		bulkTag: string;
		exportFormat: string;
		projects: LibraryProject[];
		busy: boolean;
		onApply: () => void;
		onClearSelection: () => void;
	}>();
	const workspace = getWorkspaceContext();
	const assignableProjects: LibraryProject[] = $derived(
		projects.filter((project: LibraryProject) => can(project.authorization, 'project_item.manage'))
	);
	$effect(() => {
		if (bulkProject && !assignableProjects.some((project) => project.id === bulkProject)) {
			bulkProject = '';
		}
	});
</script>

{#if selectedCount}
	<section
		class="sticky top-3 z-30 mt-4 flex flex-wrap items-center gap-2 rounded-xl border border-primary-700-300/30 bg-surface-50-950 p-3 shadow-lg"
	>
		<strong class="mr-2">{$t('{count} selected', { count: selectedCount })}</strong>
		<select class="input w-auto min-w-36" bind:value={bulkAction} aria-label={$t('Bulk action')}>
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
				class="w-auto min-w-48"
				label={$t('Select Project')}
				emptyLabel={$t('Select Project')}
				bind:value={bulkProject}
				disabled={busy}
				options={assignableProjects.map((project: LibraryProject) => ({
					value: project.id,
					label: project.name
				}))}
			/>
		{/if}
		{#if bulkAction === 'add_tag'}<input
				class="input w-auto min-w-36"
				bind:value={bulkTag}
				placeholder={$t('Tag name')}
			/>{/if}
		{#if bulkAction === 'bibliography'}<select
				class="input w-auto min-w-36"
				bind:value={exportFormat}
			>
				{#each bibliographyFormats as choice (choice.value)}
					<option value={choice.value}>{$t(choice.label)}</option>
				{/each}
			</select>{/if}
		<Button
			variant="filled"
			disabled={busy ||
				!bulkAction ||
				!canRunBulkAction(
					workspace.can,
					bulkAction as import('#lib/features/library/mutations.js').LibraryBulkAction
				) ||
				(bulkAction === 'add_project' && !bulkProject) ||
				(bulkAction === 'add_tag' && !bulkTag.trim())}
			onclick={onApply}>{$t('Apply')}</Button
		>
		<Button onclick={onClearSelection}>{$t('Clear selection')}</Button>
	</section>
{/if}
