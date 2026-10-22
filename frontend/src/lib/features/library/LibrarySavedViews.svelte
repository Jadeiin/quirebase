<script lang="ts">
	import { beforeNavigate } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { onDestroy, onMount, tick, untrack } from 'svelte';
	import { Dialog, Portal } from '@skeletonlabs/skeleton-svelte';
	import Button from '#lib/design/Button.svelte';
	import { buttonClass } from '#lib/design/button-classes.js';
	import DialogCloseButton from '#lib/design/DialogCloseButton.svelte';
	import Notice from '#lib/design/Notice.svelte';
	import { t } from '#lib/i18n.js';
	import { getSession } from '#lib/session.js';
	import { getWorkspaceContext } from '#lib/workspaces/context.svelte.js';
	import type { LibraryFilters } from './filters.js';
	import {
		deleteLibraryView,
		InvalidSavedViews,
		librarySavedViewsKey,
		readLibrarySavedViews,
		renameLibraryView,
		resetInvalidLibrarySavedViews,
		savedLibraryViewHref,
		savedViewNameLimit,
		saveLibraryView,
		type LibrarySavedView
	} from './saved-views.js';

	let { filters, pageSize }: { filters: LibraryFilters; pageSize: number } = $props();
	const { workspaceId } = getWorkspaceContext();
	const session = getSession().query;
	const storageKey = $derived(
		session.data?.user?.id ? librarySavedViewsKey(session.data.user.id, workspaceId) : ''
	);
	let open = $state(false);
	let restoreFocus = $state(true);
	let views = $state<LibrarySavedView[]>([]);
	let name = $state('');
	let editingId = $state('');
	let renamed = $state('');
	let error = $state('');
	let loadFailed = $state(false);
	let damaged = $state(false);
	let notice = $state('');
	let pending = $state(false);
	let interaction = 0;
	let mounted = true;
	let nameInput = $state<HTMLInputElement>();
	let renameInput = $state<HTMLInputElement>();
	let renameForm = $state<HTMLFormElement>();
	let renameTrigger: HTMLElement | undefined;
	const viewLinks: Record<string, HTMLAnchorElement | undefined> = Object.create(null);
	let snapshot: { filters: LibraryFilters; pageSize: number } | null = null;

	function isCurrent(version: number, key = storageKey) {
		return mounted && open && interaction === version && storageKey === key;
	}

	function focusRemainingView(index: number) {
		const id = views[Math.min(index, views.length - 1)]?.id;
		const version = interaction;
		const key = storageKey;
		void tick().then(() => {
			if (isCurrent(version, key) && document.activeElement === document.body)
				((id && viewLinks[id]) || nameInput)?.focus();
		});
	}

	function load(feedback = true) {
		if (!storageKey) return;
		const focusedIndex = views.findIndex((view) =>
			viewLinks[view.id]?.closest('[data-saved-view-row]')?.contains(document.activeElement)
		);
		const focusedId = views[focusedIndex]?.id;
		try {
			views = readLibrarySavedViews(localStorage, storageKey);
			if (!views.some((view) => view.id === editingId)) editingId = '';
			if (focusedId && !views.some((view) => view.id === focusedId))
				focusRemainingView(focusedIndex);
			if (feedback) {
				error = '';
				loadFailed = damaged = false;
			}
		} catch (reason) {
			if (feedback) {
				error = $t('Unable to load saved views.');
				loadFailed = true;
				damaged = reason instanceof InvalidSavedViews;
			}
		}
	}

	$effect(() => {
		const key = storageKey;
		untrack(() => {
			interaction++;
			pending = false;
			views = [];
			name = editingId = renamed = error = notice = '';
			loadFailed = damaged = false;
			snapshot = null;
			if (open && key) {
				snapshot = { filters: { ...filters }, pageSize };
				load();
			}
		});
	});

	onMount(() => {
		const changed = (event: StorageEvent) => {
			if (event.key === storageKey || event.key === null) load();
		};
		window.addEventListener('storage', changed);
		return () => window.removeEventListener('storage', changed);
	});
	beforeNavigate(() => {
		interaction++;
		pending = false;
		restoreFocus = false;
		open = false;
	});
	onDestroy(() => {
		mounted = false;
		interaction++;
	});

	function setOpen(next: boolean) {
		if (next === open) return;
		interaction++;
		pending = false;
		open = next;
		if (next) {
			restoreFocus = true;
			notice = '';
			snapshot = { filters: { ...filters }, pageSize };
			load();
		}
	}

	async function change(operation: (key: string) => Promise<LibrarySavedView[]>, message: string) {
		const key = storageKey;
		const version = interaction;
		if (!key || pending || !open) return false;
		pending = true;
		error = notice = '';
		try {
			const next = await operation(key);
			if (!isCurrent(version, key)) {
				// Reopening this dialog must retain its new draft and feedback while
				// reflecting a write completed by its previous interaction.
				if (mounted && open && storageKey === key && !pending) load(false);
				return false;
			}
			views = next;
			error = '';
			loadFailed = damaged = false;
			notice = message;
			return true;
		} catch (reason) {
			if (!isCurrent(version, key)) return false;
			error = $t('Unable to update saved views.');
			loadFailed = false;
			damaged = reason instanceof InvalidSavedViews;
			notice = '';
			return false;
		} finally {
			if (isCurrent(version, key)) pending = false;
		}
	}

	async function save(event: SubmitEvent) {
		event.preventDefault();
		const current = snapshot;
		const nextName = name;
		if (!nextName.trim() || !current) return;
		if (
			await change(
				(key) =>
					saveLibraryView(() => localStorage, key, nextName, current.filters, current.pageSize),
				$t('View saved')
			)
		)
			name = '';
	}

	function startRename(view: LibrarySavedView, trigger: HTMLElement) {
		if (pending) return;
		const version = interaction;
		const key = storageKey;
		editingId = view.id;
		renamed = view.name;
		renameTrigger = trigger;
		void tick().then(() => {
			if (isCurrent(version, key) && editingId === view.id) {
				renameInput?.focus();
				renameInput?.select();
			}
		});
	}

	function stopRename(restore = renameForm?.contains(document.activeElement)) {
		if (pending) return;
		const version = interaction;
		const key = storageKey;
		const id = editingId;
		editingId = '';
		void tick().then(() => {
			if (isCurrent(version, key) && restore && document.activeElement === document.body)
				(renameTrigger?.isConnected ? renameTrigger : (viewLinks[id] ?? nameInput))?.focus();
		});
	}

	async function rename(event: SubmitEvent, id: string) {
		event.preventDefault();
		const nextName = renamed;
		const restore = renameForm?.contains(document.activeElement);
		if (!nextName.trim()) return;
		if (
			await change(
				(key) => renameLibraryView(() => localStorage, key, id, nextName),
				$t('View renamed')
			)
		)
			stopRename(restore);
	}

	async function remove(id: string) {
		const index = views.findIndex((view) => view.id === id);
		const restore = viewLinks[id]
			?.closest('[data-saved-view-row]')
			?.contains(document.activeElement);
		if (await change((key) => deleteLibraryView(() => localStorage, key, id), $t('View deleted'))) {
			if (editingId === id) editingId = '';
			if (restore) focusRemainingView(index);
		}
	}
</script>

<Dialog
	{open}
	{restoreFocus}
	initialFocusEl={() => nameInput ?? null}
	onOpenChange={(details) => setOpen(details.open)}
>
	<Dialog.Trigger class={buttonClass('tonal', 'sm')}>{$t('Saved views')}</Dialog.Trigger>
	<Portal>
		<Dialog.Backdrop class="fixed inset-0 z-70 bg-surface-950/45 backdrop-blur-[2px]" />
		<Dialog.Positioner class="fixed inset-0 z-71 grid grid-cols-1 place-items-center p-4">
			<Dialog.Content
				aria-busy={pending}
				class="max-h-[85dvh] w-full max-w-lg overflow-y-auto rounded-container border border-surface-300-700 bg-surface-50-950 p-5 shadow-2xl"
			>
				<header class="flex items-start justify-between gap-3">
					<Dialog.Title class="text-lg font-bold">{$t('Saved views')}</Dialog.Title>
					<DialogCloseButton />
				</header>
				<Dialog.Description class="mt-2 text-sm text-surface-600-400">
					{$t('Saved in this browser for this account and Workspace.')}
				</Dialog.Description>
				<form class="mt-4 flex flex-wrap items-end gap-2" onsubmit={save}>
					<label class="min-w-0 flex-1">
						{$t('View name')}
						<input
							bind:this={nameInput}
							bind:value={name}
							class="input"
							maxlength={savedViewNameLimit}
							readonly={pending}
							required
						/>
					</label>
					<Button type="submit" variant="filled" disabled={pending || !name.trim() || !storageKey}
						>{$t('Save current view')}</Button
					>
				</form>
				<p class="mt-2 text-xs text-surface-600-400">
					{$t('Saves the current filters, sort order, and page size.')}
				</p>
				{#if error}
					<Notice as="div" variant="error" class="my-4">
						<p>{error}</p>
						{#if loadFailed}<Button size="sm" disabled={pending} onclick={() => load()}
								>{$t('Retry')}</Button
							>{/if}
						{#if damaged}
							<Button
								size="sm"
								disabled={pending}
								onclick={() =>
									change(
										(key) => resetInvalidLibrarySavedViews(() => localStorage, key),
										$t('Saved views reset')
									)}>{$t('Reset saved views')}</Button
							>
						{/if}
					</Notice>
				{/if}
				{#if pending}<p class="mt-3 text-sm text-surface-600-400" role="status">
						{$t('Applying action…')}
					</p>{/if}
				{#if notice}<p class="mt-3 text-sm text-success-700-300" role="status">{notice}</p>{/if}
				<ul class="mt-4 grid grid-cols-1 divide-y divide-surface-300-700">
					{#each views as view (view.id)}
						<li class="py-3" data-saved-view-row>
							<div role="group" aria-label={view.name}>
								<div class="flex flex-wrap items-center gap-2">
									<a
										bind:this={viewLinks[view.id]}
										href={resolve(savedLibraryViewHref(workspaceId, view))}
										class="min-w-0 flex-1 font-semibold break-words">{view.name}</a
									>
									<Button
										size="sm"
										disabled={pending}
										aria-label={$t('Rename {name}', { name: view.name })}
										onclick={(event) => startRename(view, event.currentTarget)}
										>{$t('Rename')}</Button
									>
									<Button
										size="sm"
										disabled={pending}
										variant="danger"
										aria-label={$t('Delete {name}', { name: view.name })}
										onclick={() => remove(view.id)}>{$t('Delete')}</Button
									>
								</div>
								{#if editingId === view.id}
									<form
										bind:this={renameForm}
										class="mt-3 flex flex-wrap items-end gap-2"
										onsubmit={(event) => rename(event, view.id)}
									>
										<label class="min-w-0 flex-1">
											{$t('New name')}<input
												bind:this={renameInput}
												class="input"
												bind:value={renamed}
												maxlength={savedViewNameLimit}
												readonly={pending}
												required
											/>
										</label>
										<Button type="submit" disabled={pending || !renamed.trim()}
											>{$t('Save name')}</Button
										>
										<Button type="button" disabled={pending} onclick={() => stopRename()}
											>{$t('Cancel')}</Button
										>
									</form>
								{/if}
							</div>
						</li>
					{:else}
						{#if !error}
							<li class="py-4 text-sm text-surface-600-400">{$t('No saved views yet.')}</li>
						{/if}
					{/each}
				</ul>
			</Dialog.Content>
		</Dialog.Positioner>
	</Portal>
</Dialog>
