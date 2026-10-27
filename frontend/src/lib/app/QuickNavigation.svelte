<script lang="ts">
	import { beforeNavigate } from '$app/navigation';
	import { page } from '$app/state';
	import { Dialog, Portal } from '@skeletonlabs/skeleton-svelte';
	import { createHotkeys } from '@tanstack/svelte-hotkeys';
	import { tick } from 'svelte';
	import type { components } from '#lib/api/schema.js';
	import { hasAllowedAction } from '#lib/authorization/can.js';
	import DialogCloseButton from '#lib/design/DialogCloseButton.svelte';
	import QueryError from '#lib/design/QueryError.svelte';
	import { t } from 'lingui-for-svelte/macro';
	import { canOpenQuickNavigation } from './quick-navigation.js';

	let {
		open = $bindable(false),
		workspaceId,
		user
	}: {
		open?: boolean;
		workspaceId?: string;
		user?: components['schemas']['SessionUserView'] | null;
	} = $props();
	let returnFocus: HTMLElement | null = null;
	let heading = $state<HTMLHeadingElement>();
	let content = $state<HTMLDivElement>();
	let dialogModule = $state<Promise<typeof import('./QuickNavigationDialog.svelte')> | null>(null);
	let wasOpen = false;
	let previousUserId: string | null | undefined;
	const readerRoute = $derived(/\/item\/[^/]+\/pdf\/[^/]+$/.test(page.url.pathname));
	$effect(() => {
		const id = user?.id ?? null;
		if (previousUserId !== undefined && previousUserId !== id) navigating();
		previousUserId = id;
	});
	$effect(() => {
		if (open && !wasOpen) {
			returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
			dialogModule ??= import('./QuickNavigationDialog.svelte');
		}
		wasOpen = open;
	});

	createHotkeys(
		() => [
			{
				hotkey: 'Mod+K',
				callback: (event) => {
					if (!canOpenQuickNavigation(event, readerRoute)) return;
					event.preventDefault();
					open = true;
				}
			}
		],
		() => ({
			target: window,
			enabled: !open,
			preventDefault: false,
			stopPropagation: false,
			ignoreInputs: false,
			requireReset: false
		})
	);

	function navigating() {
		returnFocus = null;
		open = false;
	}
	beforeNavigate(navigating);

	function finalFocus() {
		if (returnFocus?.isConnected) return returnFocus;
		// The trap snapshots restoreFocus on opening, but reads this target during cleanup.
		// Returning the current element preserves navigation focus without its trigger fallback.
		return document.activeElement instanceof HTMLElement ? document.activeElement : document.body;
	}

	async function ready(input: HTMLInputElement) {
		await tick();
		if (open && input.isConnected && document.activeElement === heading) input.focus();
	}
</script>

{#snippet loading()}
	<p role="status" class="py-6 text-sm text-surface-600-400">{$t`Loading navigation…`}</p>
{/snippet}

<Dialog
	{open}
	initialFocusEl={() => content?.querySelector<HTMLInputElement>('input') ?? heading ?? null}
	finalFocusEl={finalFocus}
	onOpenChange={(details) => (open = details.open)}
>
	<Portal>
		<Dialog.Backdrop class="fixed inset-0 z-70 bg-surface-950/45 backdrop-blur-[2px]" />
		<Dialog.Positioner class="fixed inset-0 z-71 grid grid-cols-1 place-items-center p-4">
			<Dialog.Content
				class="max-h-[85dvh] w-full max-w-2xl overflow-y-auto rounded-container border border-surface-300-700 bg-surface-50-950 p-5 shadow-2xl"
			>
				<div bind:this={content}>
					<header class="flex items-start justify-between gap-3">
						<Dialog.Title class="text-lg font-bold">
							{#snippet element(attributes)}
								<h2 {...attributes} bind:this={heading} tabindex="-1">{$t`Quick navigation`}</h2>
							{/snippet}
						</Dialog.Title>
						<DialogCloseButton />
					</header>
					<Dialog.Description class="mt-2 text-sm text-surface-600-400">
						{$t`Go to a page, Workspace, or Project.`}
					</Dialog.Description>
					{#if open}
						{#if dialogModule}
							{#await dialogModule}
								{@render loading()}
							{:then { default: QuickNavigationDialog }}
								{#key workspaceId}
									<QuickNavigationDialog
										{workspaceId}
										administration={hasAllowedAction(user?.authorization)}
										onNavigate={navigating}
										onReady={ready}
									/>
								{/key}
							{:catch}
								<QueryError
									message={$t`Unable to load navigation.`}
									onRetry={() => (dialogModule = import('./QuickNavigationDialog.svelte'))}
								/>
							{/await}
						{:else}
							{@render loading()}
						{/if}
					{/if}
				</div>
			</Dialog.Content>
		</Dialog.Positioner>
	</Portal>
</Dialog>
