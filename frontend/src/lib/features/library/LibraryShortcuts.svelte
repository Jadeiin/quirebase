<script lang="ts">
	import { Dialog, Portal } from '@skeletonlabs/skeleton-svelte';
	import { createHotkeys, formatForDisplay } from '@tanstack/svelte-hotkeys';
	import { buttonClass } from '#lib/design/button-classes.js';
	import DialogCloseButton from '#lib/design/DialogCloseButton.svelte';
	import Icon from '#lib/design/Icon.svelte';
	import SectionHeader from '#lib/design/SectionHeader.svelte';
	import { getSession } from '#lib/session.js';
	import { t } from '#lib/i18n.js';
	import { libraryPreviewCommands, libraryRowCommands, runLibraryShortcut } from './shortcuts.js';

	let {
		enabled = $bindable(true),
		onSearch,
		onEscape,
		onCopy
	}: {
		enabled: boolean;
		onSearch: () => void;
		onEscape: () => boolean;
		onCopy: () => boolean;
	} = $props();
	let open = $state(false);
	let returnFocus: HTMLElement | undefined;
	const session = getSession().query;
	const preferenceKey = $derived(`quirebase:library-shortcuts:${session.data?.user?.id ?? ''}`);
	$effect(() => {
		const key = preferenceKey;
		try {
			enabled = localStorage.getItem(key) !== 'false';
		} catch {
			enabled = true;
		}
	});

	function changeEnabled(event: Event) {
		enabled = (event.currentTarget as HTMLInputElement).checked;
		try {
			localStorage.setItem(preferenceKey, String(enabled));
		} catch {
			// Shortcuts remain configurable when browser storage is unavailable.
		}
	}

	function setOpen(next: boolean) {
		if (next && !open) {
			returnFocus =
				document.activeElement instanceof HTMLElement ? document.activeElement : undefined;
		}
		open = next;
	}

	createHotkeys(
		() => [
			{
				hotkey: '/',
				callback: (event) => runLibraryShortcut(event, onSearch),
				options: { enabled: enabled && !open }
			},
			{
				hotkey: '?',
				callback: (event) => runLibraryShortcut(event, () => setOpen(true)),
				options: { enabled: enabled && !open }
			},
			{ hotkey: 'Escape', callback: (event) => runLibraryShortcut(event, onEscape) },
			{ hotkey: 'Mod+Shift+C', callback: (event) => runLibraryShortcut(event, onCopy) }
		],
		() => ({
			// Run after Skeleton's document listeners and leave unhandled events intact.
			target: window,
			enabled: !open,
			preventDefault: false,
			stopPropagation: false,
			// Filter event.repeat below; keyup may happen outside this window.
			requireReset: false,
			// Library row checkboxes remain eligible; text fields keep their keys below.
			ignoreInputs: false
		})
	);
</script>

<Dialog
	{open}
	onOpenChange={(details) => setOpen(details.open)}
	finalFocusEl={() => (returnFocus?.isConnected ? returnFocus : null)}
>
	<Dialog.Trigger
		class={buttonClass('icon')}
		aria-label={$t('Keyboard shortcuts')}
		aria-keyshortcuts={enabled ? 'Shift+/' : undefined}
		title={enabled ? $t('Keyboard shortcuts (?)') : $t('Keyboard shortcuts')}
	>
		<Icon name="keyboard" />
	</Dialog.Trigger>
	<Portal>
		<Dialog.Backdrop class="fixed inset-0 z-70 bg-surface-950/45 backdrop-blur-[2px]" />
		<Dialog.Positioner class="fixed inset-0 z-71 grid grid-cols-1 place-items-center p-4">
			<Dialog.Content
				class="max-h-[85dvh] w-full max-w-lg overflow-y-auto rounded-container border border-surface-300-700 bg-surface-50-950 p-5 shadow-2xl"
			>
				<SectionHeader>
					<Dialog.Title class="text-lg font-bold">{$t('Keyboard shortcuts')}</Dialog.Title>
					{#snippet actions()}<DialogCloseButton />{/snippet}
				</SectionHeader>
				<Dialog.Description class="mt-3 text-sm text-surface-600-400">
					{$t('Available in the Library when you are not typing in a field.')}
				</Dialog.Description>
				<dl class="my-5 grid grid-cols-[1fr_auto] items-center gap-x-4 gap-y-3 text-sm">
					<dt>{$t('Focus Library Search')}</dt>
					<dd><kbd class="kbd">/</kbd></dd>
					<dt>{$t('Show keyboard shortcuts')}</dt>
					<dd><kbd class="kbd">?</kbd></dd>
					<dt>{$t('Close a popup or preview, then clear selection')}</dt>
					<dd><kbd class="kbd">{formatForDisplay('Escape')}</kbd></dd>
					<dt>{$t('Copy citations for selected or focused Items')}</dt>
					<dd><kbd class="kbd">{formatForDisplay('Mod+Shift+C')}</kbd></dd>
				</dl>
				<h3 class="text-sm font-semibold">{$t('Library results')}</h3>
				<p class="mt-2 text-sm text-surface-600-400">
					{$t(
						'Focus an Item checkbox to browse and select. Selection stays on the current page. Enter on a title opens the Item.'
					)}
					{$t('Shift-click an Item checkbox to select a range on this page.')}
				</p>
				<dl class="my-5 grid grid-cols-[1fr_auto] items-center gap-x-4 gap-y-3 text-sm">
					{#each libraryRowCommands as command (command.id)}
						{@const keys = command.keys.filter((binding) => enabled || !binding.character)}
						{#if keys.length}
							<dt>{$t(command.label)}</dt>
							<dd class="flex justify-end gap-1.5">
								{#each keys as binding (binding.hotkey)}
									<kbd class="kbd">{formatForDisplay(binding.hotkey)}</kbd>
								{/each}
							</dd>
						{/if}
					{/each}
				</dl>
				<h3 class="text-sm font-semibold">{$t('Item preview')}</h3>
				<p class="mt-2 text-sm text-surface-600-400">
					{$t(
						'Focus the preview to browse the current results, including the next or previous page.'
					)}
				</p>
				<dl class="my-5 grid grid-cols-[1fr_auto] items-center gap-x-4 gap-y-3 text-sm">
					{#each libraryPreviewCommands as command (command.id)}
						<dt>{$t(command.label)}</dt>
						<dd class="flex justify-end gap-1.5">
							{#each command.keys.filter((binding) => enabled || !binding.character) as binding (binding.hotkey)}
								<kbd class="kbd">{formatForDisplay(binding.hotkey)}</kbd>
							{/each}
						</dd>
					{/each}
				</dl>
				<label class="flex items-center gap-2 border-t border-surface-300-700 pt-4 text-sm">
					<input type="checkbox" class="checkbox" checked={enabled} onchange={changeEnabled} />
					{$t('Enable letter and symbol shortcuts')}
				</label>
			</Dialog.Content>
		</Dialog.Positioner>
	</Portal>
</Dialog>
