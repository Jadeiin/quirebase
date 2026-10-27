<script lang="ts">
	import { onDestroy, untrack } from 'svelte';
	import { Dialog, Portal } from '@skeletonlabs/skeleton-svelte';
	import { createMutation, useQueryClient } from '@tanstack/svelte-query';
	import { isDownloadCancelled } from '#lib/api/client.js';
	import { apiErrorMessage } from '#lib/api/errors.js';
	import { copyBibliographyText, downloadBibliographyText } from '#lib/bibliography-copy.js';
	import Button from '#lib/design/Button.svelte';
	import DialogCloseButton from '#lib/design/DialogCloseButton.svelte';
	import Notice from '#lib/design/Notice.svelte';
	import ProjectSelect from '#lib/features/projects/ProjectSelect.svelte';
	import TagSelect from '#lib/features/tags/TagSelect.svelte';
	import {
		bibliographyFormats,
		defaultExportPreferences,
		readExportPreferences,
		type ExportPreferences
	} from '#lib/export-preferences.js';
	import { ph, t } from 'lingui-for-svelte/macro';
	import { canRunBulkAction } from '#lib/workspaces/actions.js';
	import { getWorkspaceContext } from '#lib/workspaces/context.svelte.js';
	import type { LibraryActionRequest } from './action-request.js';
	import { libraryBulkMutationOptions, type LibraryBulkInput } from './mutations.js';
	import type { ProjectSummary } from '#lib/features/projects/queries.js';

	let {
		request = $bindable<LibraryActionRequest | null>(null),
		busy = $bindable(false),
		userId,
		listingIdentity,
		onNotice
	}: {
		request?: LibraryActionRequest | null;
		busy?: boolean;
		userId: string;
		listingIdentity: string;
		onNotice: (message: string) => void;
	} = $props();

	const workspace = getWorkspaceContext();
	const { workspaceId } = workspace;
	const queryClient = useQueryClient();
	const mutation = createMutation(() => libraryBulkMutationOptions(workspaceId, queryClient));
	let active = $state<LibraryActionRequest | null>(null);
	let observedRequest: LibraryActionRequest | null = null;
	let returnFocus: HTMLElement | null = null;
	let content = $state<HTMLElement>();
	let open = $state(false);
	let restoreFocus = $state(true);
	let error = $state('');
	let projectId = $state('');
	let selectedProject = $state<ProjectSummary | null>(null);
	let tagName = $state('');
	let tagId = $state('');
	let preferences = $state<ExportPreferences>(structuredClone(defaultExportPreferences));
	let format = $state<ExportPreferences['citation']['format']>(
		defaultExportPreferences.citation.format
	);
	let frozenInput = $state<LibraryBulkInput | null>(null);
	const citationCopy = $state<{ text: string | null }>({ text: null });
	let mounted = true;
	onDestroy(() => {
		mounted = false;
	});

	$effect(() => {
		const next = request;
		const pending = busy;
		untrack(() => {
			if (next === observedRequest || pending) return;
			observedRequest = next;
			if (!next) {
				active = null;
				open = false;
				return;
			}
			active = {
				...next,
				itemIds: [...next.itemIds],
				project: next.project ? { ...next.project } : null
			};
			returnFocus = next.trigger;
			preferences = readExportPreferences(userId, workspaceId);
			format = preferences.citation.format;
			projectId = next.action === 'remove_project' ? (next.project?.id ?? '') : '';
			tagName = tagId = error = '';
			frozenInput = null;
			citationCopy.text = null;
			restoreFocus = true;
			open = next.listing === listingIdentity;
		});
	});

	$effect(() => {
		const listing = listingIdentity;
		untrack(() => {
			if (active && active.listing !== listing) dismiss(false);
		});
	});

	const bibliography = $derived(
		active?.action === 'bibliography' || active?.action === 'copy_bibliography'
	);
	const destructive = $derived(
		active?.action === 'delete_items' || active?.action === 'remove_project'
	);
	const locked = $derived(busy || frozenInput !== null);
	const validationMessage = $derived(
		!active || !active.itemIds.length || !canRunBulkAction(workspace.can, active.action)
			? $t`This action is no longer available.`
			: frozenInput
				? ''
				: active.action === 'add_project' && selectedProject?.id !== projectId
					? $t`Choose a Project.`
					: active.action === 'add_tag' && !tagName.trim()
						? $t`Choose or enter a Tag.`
						: active.action === 'remove_tag' && !tagId
							? $t`Choose a Tag.`
							: active.action === 'remove_project' && !active.project?.id
								? $t`Select a Project filter to remove Items from it.`
								: ''
	);
	const targetSummary = $derived(
		active?.source === 'item'
			? $t`Current Item`
			: $t`${ph({ count: active?.itemIds.length ?? 0 })} selected`
	);
	const title = $derived.by(() => {
		switch (active?.action) {
			case 'add_tag':
				return $t`Add Tag`;
			case 'remove_tag':
				return $t`Remove Tag`;
			case 'add_project':
				return $t`Add to Project`;
			case 'remove_project':
				return active.source === 'item'
					? $t`Remove this Item from ${ph({ project: active.project?.name ?? '' })}?`
					: $t`Remove the selected Items from ${ph({ project: active.project?.name ?? '' })}?`;
			case 'delete_items':
				return active.source === 'item'
					? $t`Permanently delete this Item?`
					: $t`Permanently delete the selected Items?`;
			case 'bibliography':
				return $t`Export bibliography`;
			case 'copy_bibliography':
				return $t`Copy citation`;
			case 'documents':
				return $t`Download documents`;
			default:
				return $t`Item actions`;
		}
	});
	const submitLabel = $derived.by(() => {
		switch (active?.action) {
			case 'remove_project':
				return $t`Remove from Project`;
			case 'delete_items':
				return $t`Permanently delete`;
			case 'bibliography':
			case 'documents':
				return $t`Download file`;
			case 'copy_bibliography':
				return $t`Copy to clipboard`;
			default:
				return title;
		}
	});

	function dismiss(restore: boolean) {
		restoreFocus = restore;
		open = false;
	}

	function close() {
		dismiss(true);
		if (!busy) {
			request = null;
			observedRequest = null;
			active = null;
			frozenInput = null;
			citationCopy.text = null;
		}
	}

	function finalFocusEl() {
		return returnFocus?.isConnected && !returnFocus.matches(':disabled, [aria-disabled="true"]')
			? returnFocus
			: document.getElementById('library-results');
	}

	function review() {
		restoreFocus = true;
		open = true;
	}

	function changeOptions() {
		if (busy) return;
		frozenInput = null;
		citationCopy.text = null;
		error = '';
		if (projectId && selectedProject?.id !== projectId) projectId = '';
	}

	function currentInput(): LibraryBulkInput | null {
		if (!active) return null;
		const itemIds = [...active.itemIds];
		switch (active.action) {
			case 'add_project':
				return { action: active.action, item_ids: itemIds, project_id: projectId };
			case 'remove_project':
				return {
					action: active.action,
					item_ids: itemIds,
					project_id: active.project?.id ?? ''
				};
			case 'add_tag':
				return { action: active.action, item_ids: itemIds, tag_name: tagName.trim() };
			case 'remove_tag':
				return { action: active.action, item_ids: itemIds, tag_id: tagId };
			case 'delete_items':
				return { action: active.action, item_ids: itemIds };
			case 'bibliography':
			case 'copy_bibliography':
				return {
					action: active.action,
					itemIds,
					exportFormat: format,
					preferences: $state.snapshot(preferences.citation)
				};
			case 'documents':
				return {
					action: active.action,
					itemIds,
					preferences: $state.snapshot(preferences.document)
				};
		}
	}

	function complete(message: string) {
		if (!mounted) return;
		// A dismissed operation must never interrupt interaction with the Library.
		if (open) {
			const focused = document.activeElement;
			dismiss(focused === document.body || Boolean(focused && content?.contains(focused)));
		}
		onNotice(message);
		request = null;
		observedRequest = null;
		active = null;
		frozenInput = null;
		citationCopy.text = null;
	}

	async function execute() {
		if (busy || !active || validationMessage) return;
		if (!canRunBulkAction(workspace.can, active.action)) return;
		const input = frozenInput ?? currentInput();
		if (!input) return;
		const submitted = active;
		frozenInput = input;
		busy = true;
		error = '';
		try {
			if (input.action === 'copy_bibliography') {
				await copyBibliographyText(
					citationCopy,
					async () => {
						const result = await mutation.mutateAsync({ input });
						if (typeof result !== 'string') throw new Error('Missing bibliography text');
						return result;
					},
					() => mounted
				);
				complete($t`Copied to clipboard`);
			} else {
				await mutation.mutateAsync({ input, afterMutation: submitted.afterMutation });
				complete(
					input.action === 'bibliography'
						? $t`Bibliography downloaded`
						: input.action === 'documents'
							? $t`Document bundle downloaded`
							: $t`Bulk action completed`
				);
			}
		} catch (reason) {
			if (!mounted) return;
			if (isDownloadCancelled(reason)) {
				frozenInput = null;
				return;
			}
			error =
				citationCopy.text !== null
					? $t`Clipboard access was denied. Copy the citation text below or download it.`
					: apiErrorMessage(reason, $t`Bulk action failed`);
		} finally {
			if (mounted) busy = false;
		}
	}

	function downloadCitation() {
		if (citationCopy.text === null || frozenInput?.action !== 'copy_bibliography') return;
		downloadBibliographyText(citationCopy.text, frozenInput.exportFormat);
		complete($t`Bibliography downloaded`);
	}
</script>

{#if active && !open}
	<Notice as="div" variant={error ? 'error' : 'info'} class="mt-4">
		<div class="flex flex-wrap items-center justify-between gap-3">
			<div>
				<strong>{title}</strong>
				<p class="m-0 text-sm">{targetSummary}</p>
				<p class="m-0 text-sm">
					{error || (busy ? $t`Applying action…` : $t`Review this action to continue.`)}
				</p>
			</div>
			<Button size="sm" onclick={review}>{$t`Review action`}</Button>
		</div>
	</Notice>
{/if}

<Dialog
	{open}
	{restoreFocus}
	{finalFocusEl}
	initialFocusEl={() =>
		content?.querySelector<HTMLElement>(
			destructive
				? '[data-library-action-cancel]'
				: 'input:not(:disabled), select:not(:disabled), [data-library-action-submit]'
		) ?? null}
	onOpenChange={(details) => {
		if (!details.open) close();
	}}
>
	<Portal>
		<Dialog.Backdrop class="fixed inset-0 z-70 bg-surface-950/45 backdrop-blur-[2px]" />
		<Dialog.Positioner class="fixed inset-0 z-71 grid grid-cols-1 place-items-center p-4">
			<Dialog.Content
				class="max-h-[calc(100dvh-2rem)] w-full max-w-lg overflow-auto rounded-container border border-surface-300-700 bg-surface-50-950 p-5 shadow-2xl"
			>
				<div bind:this={content}>
					<header class="flex items-start justify-between gap-3">
						<div>
							<Dialog.Title class="text-lg font-bold">{title}</Dialog.Title>
							<Dialog.Description class="mt-1 mb-0 text-sm text-surface-600-400">
								{targetSummary}
							</Dialog.Description>
						</div>
						<DialogCloseButton />
					</header>
					<form
						class="mt-4 grid grid-cols-1 gap-4"
						aria-busy={busy}
						onsubmit={(event) => {
							event.preventDefault();
							void execute();
						}}
					>
						{#if active?.action === 'add_tag'}
							<TagSelect
								bind:value={tagName}
								label={$t`Select Tag`}
								emptyLabel={$t`Select Tag`}
								valueBy="name"
								allowCustomValue={workspace.can('tag.create')}
								disabled={locked}
							/>
						{:else if active?.action === 'remove_tag'}
							<TagSelect
								bind:value={tagId}
								label={$t`Select Tag`}
								emptyLabel={$t`Select Tag`}
								disabled={locked}
							/>
						{:else if active?.action === 'add_project'}
							<ProjectSelect
								bind:value={projectId}
								bind:selectedProject
								label={$t`Select Project`}
								emptyLabel={$t`Select Project`}
								manageOnly
								disabled={locked}
							/>
						{:else if active?.action === 'remove_project'}
							<p class="m-0 text-sm text-surface-600-400">
								{$t`This permanently deletes their Annotations and Replies in this Project. Items, files, private Annotations, and other Projects are preserved.`}
							</p>
						{:else if active?.action === 'delete_items'}
							<p class="m-0 text-sm text-surface-600-400">{$t`This cannot be undone.`}</p>
						{:else if bibliography}
							<p class="m-0 text-sm text-surface-600-400">
								{$t`Uses your Account export settings.`}
							</p>
							<label class="grid grid-cols-1 gap-1"
								>{$t`Format`}<select class="select" bind:value={format} disabled={locked}>
									{#each bibliographyFormats as choice (choice.value)}<option value={choice.value}
											>{$t(choice.label)}</option
										>{/each}
								</select></label
							>
							{#if format === 'csl'}<p class="m-0 text-sm text-surface-600-400">
									{$t`Citation Style`}: <strong>{preferences.citation.style}</strong>
								</p>{/if}
						{:else if active?.action === 'documents'}
							<p class="m-0 text-sm text-surface-600-400">
								{$t`Uses your Account export settings.`}
							</p>
							<label class="flex items-center gap-2"
								><input
									type="checkbox"
									class="checkbox"
									bind:checked={preferences.document.includeAnnotations}
									disabled={locked}
								/>{$t`Include Annotations`}</label
							>
							<label class="flex items-center gap-2"
								><input
									type="checkbox"
									class="checkbox"
									bind:checked={preferences.document.includeSupplements}
									disabled={locked}
								/>{$t`Include supplementary files`}</label
							>
						{/if}
						{#if error}<Notice variant="error" class="m-0">{error}</Notice>{/if}
						{#if citationCopy.text !== null}
							<label class="grid grid-cols-1 gap-1"
								>{$t`Citation text`}<textarea
									class="textarea min-h-40"
									readonly
									value={citationCopy.text}></textarea></label
							>
						{/if}
						{#if busy || validationMessage}<p
								id="library-action-hint"
								role={busy ? 'status' : undefined}
								class="m-0 text-sm text-surface-600-400"
							>
								{busy ? $t`Applying action…` : validationMessage}
							</p>{/if}
						<div class="flex flex-wrap justify-end gap-2">
							{#if frozenInput && !busy}<Button type="button" onclick={changeOptions}
									>{$t`Change options`}</Button
								>{/if}
							<Button type="button" data-library-action-cancel onclick={close}
								>{busy ? $t`Continue in Library` : $t`Cancel`}</Button
							>
							{#if citationCopy.text !== null}<Button
									type="button"
									disabled={busy}
									onclick={downloadCitation}>{$t`Download file`}</Button
								>{/if}
							<Button
								type="submit"
								data-library-action-submit
								variant={destructive ? 'danger-filled' : 'filled'}
								disabled={busy || Boolean(validationMessage)}
								aria-describedby={busy || validationMessage ? 'library-action-hint' : undefined}
								>{error && citationCopy.text === null ? $t`Retry` : submitLabel}</Button
							>
						</div>
					</form>
				</div>
			</Dialog.Content>
		</Dialog.Positioner>
	</Portal>
</Dialog>
