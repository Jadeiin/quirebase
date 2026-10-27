<script lang="ts">
	import { Menu, Portal } from '@skeletonlabs/skeleton-svelte';
	import { buttonClass } from '#lib/design/button-classes.js';
	import Icon from '#lib/design/Icon.svelte';
	import { ph, t } from 'lingui-for-svelte/macro';
	import { canRunBulkAction } from '#lib/workspaces/actions.js';
	import { getWorkspaceContext } from '#lib/workspaces/context.svelte.js';
	import {
		libraryPrimaryActions,
		librarySecondaryActions,
		type LibraryActionHandler
	} from './actions.js';

	let {
		onAction,
		disabled = false,
		currentProject = null,
		itemId,
		label,
		secondaryOnly = false,
		selectedCount = 0
	}: {
		onAction: LibraryActionHandler;
		disabled?: boolean;
		currentProject?: { id: string; name: string } | null;
		itemId?: string;
		label?: string;
		secondaryOnly?: boolean;
		selectedCount?: number;
	} = $props();
	const workspace = getWorkspaceContext();
	let trigger: HTMLButtonElement | undefined = $state();
	const availableActions = $derived(
		[...(secondaryOnly ? [] : libraryPrimaryActions), ...librarySecondaryActions].filter(
			(entry) =>
				canRunBulkAction(workspace.can, entry.action) &&
				(entry.action !== 'remove_project' || currentProject !== null)
		)
	);
</script>

{#if availableActions.length}
	<Menu positioning={{ placement: 'bottom-end', gutter: 6 }}>
		<Menu.Trigger {disabled}>
			{#snippet element(attributes)}
				<button
					{...attributes}
					bind:this={trigger}
					class={secondaryOnly ? buttonClass('tonal', 'sm') : buttonClass('icon', 'sm')}
					data-library-item-actions={itemId}
					data-library-selection-actions={secondaryOnly ? '' : undefined}
					aria-label={label ?? (secondaryOnly ? $t`More actions` : $t`Item actions`)}
					aria-keyshortcuts={itemId ? 'Shift+F10' : undefined}
					title={label ?? (secondaryOnly ? $t`More actions` : $t`Item actions`)}
				>
					<Icon name="more" size={18} />
					{#if secondaryOnly}<span>{$t`More`}</span>{/if}
				</button>
			{/snippet}
		</Menu.Trigger>
		<Portal>
			<Menu.Positioner>
				<!-- Zag copies its first child's stacking layer onto the positioned popup. -->
				<Menu.Content
					class="z-60 max-h-[min(70vh,32rem)] w-64 max-w-[calc(100vw-2rem)] min-w-0 overflow-y-auto border-surface-300-700 p-1 shadow-xl"
				>
					<div class="px-2.5 py-2 text-xs font-semibold text-surface-600-400">
						{itemId ? $t`Current Item` : $t`${ph({ count: selectedCount })} selected`}
					</div>
					{#each availableActions as entry (entry.action)}
						{#if entry.action === 'remove_tag' || entry.action === 'delete_items'}
							<Menu.Separator class="my-1 h-px bg-surface-300-700" />
						{/if}
						<Menu.Item
							value={entry.action}
							{disabled}
							class={[
								'min-w-0 cursor-pointer justify-start gap-2 rounded-sm px-2.5 py-2 text-sm outline-none data-[disabled]:cursor-default data-[disabled]:opacity-50 data-[highlighted]:bg-primary-50-950 data-[highlighted]:text-primary-800-200',
								{ 'text-error-700-300': entry.action === 'delete_items' }
							]}
							onclick={() => {
								if (trigger && !disabled) onAction(entry.action, trigger);
							}}
						>
							<Icon name={entry.icon} size={16} />
							<span>{$t(entry.label)}</span>
						</Menu.Item>
					{/each}
				</Menu.Content>
			</Menu.Positioner>
		</Portal>
	</Menu>
{/if}
