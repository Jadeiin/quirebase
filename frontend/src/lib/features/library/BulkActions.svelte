<script lang="ts">
	import type { LibraryProject } from '$lib/features/library/queries';
	import { t } from '$lib/i18n';
	import Button from '$lib/design/Button.svelte';
	import { canRunBulkAction } from '$lib/workspaces/actions';
	import { getWorkspaceContext } from '$lib/workspaces/context.svelte';

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
		{#if bulkAction === 'add_project'}<select
				class="input w-auto min-w-36"
				bind:value={bulkProject}
				aria-label={$t('Select Project')}
				><option value="">{$t('Select Project')}</option
				>{#each projects as option (option.id)}<option value={option.id}>{option.name}</option
					>{/each}</select
			>{/if}
		{#if bulkAction === 'add_tag'}<input
				class="input w-auto min-w-36"
				bind:value={bulkTag}
				placeholder={$t('Tag name')}
			/>{/if}
		{#if bulkAction === 'bibliography'}<select
				class="input w-auto min-w-36"
				bind:value={exportFormat}
				><option value="bibtex">BibTeX</option><option value="biblatex">BibLaTeX</option><option
					value="ris">RIS</option
				><option value="endnote">EndNote</option><option value="csl">CSL</option></select
			>{/if}
		<Button
			variant="filled"
			disabled={busy ||
				!bulkAction ||
				!canRunBulkAction(
					workspace.can,
					bulkAction as import('$lib/features/library/mutations').LibraryBulkAction
				) ||
				(bulkAction === 'add_project' && !bulkProject) ||
				(bulkAction === 'add_tag' && !bulkTag.trim())}
			onclick={onApply}>{$t('Apply')}</Button
		>
		<Button onclick={onClearSelection}>{$t('Clear selection')}</Button>
	</section>
{/if}
