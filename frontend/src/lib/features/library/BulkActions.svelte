<script lang="ts">
	import Button from '#lib/design/Button.svelte';
	import Icon from '#lib/design/Icon.svelte';
	import { t } from '#lib/i18n.js';
	import { canRunBulkAction } from '#lib/workspaces/actions.js';
	import { getWorkspaceContext } from '#lib/workspaces/context.svelte.js';
	import LibraryActionMenu from './LibraryActionMenu.svelte';
	import { libraryPrimaryActions, type LibraryActionHandler } from './actions.js';

	let {
		element = $bindable(),
		selectedCount,
		currentProject = null,
		busy,
		onAction,
		onClearSelection
	}: {
		element?: HTMLElement;
		selectedCount: number;
		currentProject?: { id: string; name: string } | null;
		busy: boolean;
		onAction: LibraryActionHandler;
		onClearSelection: () => void;
	} = $props();
	const workspace = getWorkspaceContext();
</script>

{#if selectedCount}
	<section
		bind:this={element}
		data-library-bulk-actions
		aria-label={$t('Bulk actions')}
		aria-busy={busy}
		class="sticky top-20 z-30 mt-4 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border border-primary-700-300/30 bg-surface-50-950 p-3 shadow-lg lg:top-3"
	>
		<div class="mr-auto min-w-0">
			<strong aria-live="polite">{$t('{count} selected', { count: selectedCount })}</strong>
			<p class="m-0 text-xs text-surface-600-400">{$t('Current page only')}</p>
		</div>
		<Button class="xl:order-2" size="sm" onclick={onClearSelection}>{$t('Clear selection')}</Button>
		<div class="flex basis-full flex-wrap items-center gap-2 xl:order-1 xl:basis-auto">
			{#each libraryPrimaryActions as entry (entry.action)}
				{#if canRunBulkAction(workspace.can, entry.action)}
					<Button
						size="sm"
						disabled={busy}
						onclick={(event) => onAction(entry.action, event.currentTarget)}
					>
						<Icon name={entry.icon} size={16} />
						{$t(entry.label)}
					</Button>
				{/if}
			{/each}
			<LibraryActionMenu
				{onAction}
				{currentProject}
				{selectedCount}
				disabled={busy}
				secondaryOnly
			/>
		</div>
		{#if busy}
			<p class="m-0 basis-full text-xs text-surface-600-400">
				{$t('Applying action…')}
			</p>
		{/if}
	</section>
{/if}
