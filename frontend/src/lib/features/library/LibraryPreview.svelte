<script lang="ts">
	import { resolve } from '$app/paths';
	import { onMount } from 'svelte';
	import { createHotkeys } from '@tanstack/svelte-hotkeys';
	import { createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { itemKeys, itemOverviewQuery } from '#lib/features/item/queries.js';
	import {
		contributorName,
		identifierRows,
		object,
		objects,
		text
	} from '#lib/features/item/metadata-draft.js';
	import { apiErrorMessage } from '#lib/api/errors.js';
	import Button from '#lib/design/Button.svelte';
	import Icon from '#lib/design/Icon.svelte';
	import Panel from '#lib/design/Panel.svelte';
	import QueryError from '#lib/design/QueryError.svelte';
	import RichText from '#lib/design/RichText.svelte';
	import { t } from '#lib/i18n.js';
	import { workspaceHref } from '#lib/workspaces/href.js';
	import type { LibraryMetadataFilter } from './filters';
	import type { LibraryPreviewNavigation } from './preview-navigation.js';
	import { libraryPreviewCommands, runLibraryShortcut } from './shortcuts.js';
	import LibraryActionMenu from './LibraryActionMenu.svelte';
	import type { LibraryActionHandler } from './actions.js';
	let {
		workspaceId,
		itemId,
		onClose,
		onReady,
		navigation,
		shortcutsEnabled = true,
		itemHref,
		filterHref,
		currentProject,
		actionsBusy,
		onAction
	}: {
		workspaceId: string;
		itemId: string;
		onClose: () => void;
		onReady: (heading: HTMLHeadingElement) => void;
		navigation?: LibraryPreviewNavigation;
		shortcutsEnabled?: boolean;
		itemHref: (suffix?: string) => ReturnType<typeof workspaceHref>;
		filterHref: (
			filter: LibraryMetadataFilter | { tag: string }
		) => ReturnType<typeof workspaceHref>;
		currentProject: { id: string; name: string } | null;
		actionsBusy: boolean;
		onAction: LibraryActionHandler;
	} = $props();
	const queryClient = useQueryClient();
	const item = createQuery(() => itemOverviewQuery(workspaceId, itemId));
	let heading: HTMLHeadingElement;
	let previewElement: HTMLElement;
	let organizeOpen = $state(false);
	let organizeModule = $state<Promise<typeof import('./LibraryPreviewOrganize.svelte')>>();
	let copyStatus = $state('');
	let refreshing = $state(false);
	const contributors = $derived.by(() => {
		const rows = objects(item.data?.metadata.contributors);
		const authors = rows.filter((row) => Array.isArray(row.roles) && row.roles.includes('Author'));
		return (
			authors.length
				? authors
				: rows.filter((row) => Array.isArray(row.roles) && row.roles.includes('Editor'))
		)
			.map(contributorName)
			.filter(Boolean)
			.join('; ');
	});
	const authors = $derived(
		objects(item.data?.metadata.contributors)
			.filter((row) => Array.isArray(row.roles) && row.roles.includes('Author'))
			.map((row) => {
				const entity = object(row[row.type === 'Person' ? 'person' : 'organization']);
				const family = row.type === 'Person' ? text(entity.family_name) : '';
				return {
					label: contributorName(row),
					filter: {
						author_last_name: family || text(entity.name) || text(entity.given_name),
						author_first_name: family ? text(entity.given_name) : ''
					}
				};
			})
			.filter((author) => author.label)
	);
	const publicationTitle = $derived(text(object(item.data?.metadata.container).title));
	const publication = $derived(
		publicationTitle || text(object(item.data?.metadata.publisher).name)
	);
	const doi = $derived(
		item.data &&
			(identifierRows(item.data.metadata).find((row) => row.namespace === 'doi')?.value ||
				text(item.data.metadata.id).match(/^https?:\/\/(?:dx\.)?doi\.org\/(.+)$/i)?.[1] ||
				'')
	);
	const publicationDate = $derived(text(item.data?.metadata.date_published));
	const publicationYear = $derived(
		/^\d{4}(?:-|$)/.test(publicationDate) ? publicationDate.slice(0, 4) : ''
	);
	onMount(() => onReady(heading));

	function move(direction: 'previous' | 'next') {
		if (
			!navigation ||
			navigation.busy ||
			!(direction === 'previous' ? navigation.canPrevious : navigation.canNext)
		)
			return false;
		navigation[direction]();
		return true;
	}

	createHotkeys(
		() =>
			libraryPreviewCommands.flatMap((command) =>
				command.keys.map((binding) => ({
					hotkey: binding.hotkey,
					callback: (event: KeyboardEvent) =>
						runLibraryShortcut(
							event,
							() => {
								if (!previewElement?.contains(document.activeElement)) return false;
								if (command.id === 'actions') {
									const menu = previewElement.querySelector<HTMLButtonElement>(
										'[data-library-item-actions]'
									);
									if (!menu || menu.disabled) return false;
									menu.focus();
									menu.click();
									return true;
								}
								return move(command.id);
							},
							command.repeat
						),
					options: { enabled: !binding.character || shortcutsEnabled }
				}))
			),
		() => ({
			target: window,
			preventDefault: false,
			stopPropagation: false,
			requireReset: false,
			ignoreInputs: false
		})
	);

	async function copyDoi() {
		if (!doi) return;
		copyStatus = '';
		try {
			await navigator.clipboard.writeText(doi);
			copyStatus = $t('Copied to clipboard');
		} catch {
			copyStatus = $t('Unable to copy DOI. Select and copy it manually.');
		}
	}

	function toggleOrganize() {
		organizeOpen = !organizeOpen;
		if (organizeOpen && !organizeModule) organizeModule = import('./LibraryPreviewOrganize.svelte');
	}

	async function refreshPreview() {
		if (refreshing) return;
		refreshing = true;
		try {
			await queryClient.invalidateQueries({ queryKey: itemKeys.detail(workspaceId, itemId) });
		} finally {
			refreshing = false;
		}
	}
	let positioned = false;
	$effect(() => {
		if (item.isPending || positioned) return;
		positioned = true;
		// Loading content can move the preview through browser scroll anchoring.
		if (document.activeElement === heading) heading.scrollIntoView({ block: 'nearest' });
	});
</script>

<aside
	id="library-preview"
	aria-labelledby="library-preview-heading"
	class="min-w-0 max-xl:order-first xl:sticky xl:top-4"
	bind:this={previewElement}
>
	<Panel padding="none">
		<header class="border-b border-surface-300-700 px-4 py-3">
			<div class="flex items-center justify-between gap-2">
				<h2
					id="library-preview-heading"
					class="scroll-mt-20 text-base font-semibold focus:outline-none"
					tabindex="-1"
					bind:this={heading}
				>
					{$t('Item preview')}
				</h2>
				<div class="flex items-center gap-1">
					<Button
						variant="icon"
						size="sm"
						disabled={refreshing || item.isFetching}
						aria-label={$t('Refresh preview')}
						onclick={() => void refreshPreview()}><Icon name="rotate" size={16} /></Button
					>
					<Button
						variant="icon"
						size="sm"
						aria-label={$t('Close preview')}
						aria-keyshortcuts="Escape"
						title={$t('Close preview')}
						onclick={onClose}><Icon name="close" size={16} /></Button
					>
				</div>
			</div>
			{#if navigation}
				<div
					class="mt-2 flex items-center justify-between gap-2"
					aria-label={$t('Preview navigation')}
					aria-busy={navigation.busy}
				>
					<p class="text-xs text-surface-600-400" aria-live="polite">
						{#if navigation.position !== null}{$t('Item {position} of {total}', {
								position: navigation.position,
								total: navigation.total
							})}{:else}{$t('Outside current results')}{/if}
					</p>
					<div class="flex items-center gap-1">
						<Button
							variant="icon"
							size="sm"
							aria-label={$t('Previous Item')}
							title={$t('Previous Item')}
							disabled={navigation.busy || !navigation.canPrevious}
							onclick={() => move('previous')}><Icon name="chevron-left" size={16} /></Button
						>
						<Button
							variant="icon"
							size="sm"
							aria-label={$t('Next Item')}
							title={$t('Next Item')}
							disabled={navigation.busy || !navigation.canNext}
							onclick={() => move('next')}><Icon name="chevron-right" size={16} /></Button
						>
					</div>
				</div>
				{#if navigation.error}<QueryError
						message={navigation.error}
						busy={navigation.busy}
						onRetry={navigation.retry}
					/>{/if}
			{/if}
		</header>
		<div class="max-h-[70vh] overflow-y-auto p-4">
			{#if item.isPending}<p class="text-sm text-surface-600-400" role="status">
					{$t('Loading Item preview…')}
				</p>
			{:else if item.isError}<QueryError
					message={apiErrorMessage(item.error, $t('Unable to load this Item preview.'))}
					busy={item.isFetching}
					onRetry={() => void item.refetch()}
				/>
			{:else if item.data}
				<h3 class="mb-3 text-lg leading-relaxed break-words">
					<RichText html={item.data.metadata.title || ''} />
				</h3>
				<p class="mb-2 text-sm leading-6 break-words text-surface-700-300">
					{#each authors as author, index (index)}
						{index ? '; ' : ''}<a
							class="text-inherit no-underline hover:text-primary-700-300 hover:underline focus-visible:underline"
							href={resolve(filterHref(author.filter))}
							title={$t('View Items by {name}', { name: author.label })}>{author.label}</a
						>
					{:else}{contributors || $t('Unknown authors')}{/each}
				</p>
				<p class="mb-4 text-sm leading-6 break-words text-surface-600-400">
					{#if publicationTitle}<a
							class="text-inherit no-underline hover:text-primary-700-300 hover:underline focus-visible:underline"
							href={resolve(filterHref({ publication_title: publication }))}
							title={$t('View Items in {name}', { name: publication })}>{publication}</a
						>{:else}{publication}{/if}
					{publication && publicationDate ? ' · ' : ''}
					{#if publicationYear}<a
							class="text-inherit no-underline hover:text-primary-700-300 hover:underline focus-visible:underline"
							href={resolve(filterHref({ year: publicationYear }))}
							title={$t('View Items published in {year}', { year: publicationYear })}
							>{publicationYear}</a
						>{publicationDate.slice(4)}{:else}{publicationDate}{/if}
					{!publication && !publicationDate ? '—' : ''}
				</p>
				<div class="flex flex-wrap gap-2">
					{#if item.data.latest_revision_id}<Button
							as="a"
							variant="primary"
							href={resolve(itemHref(`pdf/${item.data.latest_revision_id}`))}
							><Icon name="file" size={16} />{$t('Read PDF')}</Button
						>{/if}
					<Button as="a" href={resolve(itemHref())}>{$t('Open full details')}</Button>
					<LibraryActionMenu {itemId} {currentProject} {onAction} disabled={actionsBusy} />
				</div>
				{#if doi}
					<div class="mt-3 flex flex-wrap items-center gap-2 text-xs">
						<span class="min-w-0 break-all text-surface-600-400">{$t('DOI')}: {doi}</span>
						<Button size="sm" onclick={() => void copyDoi()}>{$t('Copy DOI')}</Button>
					</div>
					{#if copyStatus}<p role="status" class="mt-1 text-xs text-surface-600-400">
							{copyStatus}
						</p>{/if}
				{/if}
				<section class="mt-6 border-t border-surface-300-700 pt-4">
					<h3 class="mb-2 text-sm font-semibold">{$t('Abstract')}</h3>
					<div class="text-sm leading-7 break-words text-surface-700-300">
						{#if item.data.metadata.description}<RichText
								html={item.data.metadata.description}
							/>{:else}<p class="m-0 text-surface-600-400">{$t('No abstract available.')}</p>{/if}
					</div>
				</section>
				<section class="mt-5 border-t border-surface-300-700 pt-4">
					<div class="mb-3 flex items-center justify-between gap-2">
						<h3 class="text-sm font-semibold">{$t('Tags')}</h3>
						<Button
							size="sm"
							aria-expanded={organizeOpen}
							aria-controls="preview-organize-content"
							onclick={toggleOrganize}>{$t('Organize this Item')}</Button
						>
					</div>
					{#if !organizeOpen}
						<div class="flex flex-wrap gap-2">
							{#each item.data.tags as tag (tag.id)}<a
									class="max-w-full rounded-full bg-primary-50-950 px-2.5 py-1 text-xs font-semibold break-words text-primary-800-200"
									href={resolve(filterHref({ tag: tag.id }))}>{tag.name}</a
								>{:else}<span class="text-sm text-surface-600-400">{$t('No tags')}</span>{/each}
						</div>
					{/if}
					<div id="preview-organize-content" hidden={!organizeOpen}>
						{#if organizeModule}
							<p class="text-xs text-surface-600-400">
								{$t('Changes apply only to the Item in this preview.')}
							</p>
							{#await organizeModule}<p role="status" class="mt-3 text-sm text-surface-600-400">
									{$t('Loading organization options…')}
								</p>
							{:then { default: LibraryPreviewOrganize }}
								{#key `${workspaceId}:${itemId}`}<LibraryPreviewOrganize
										{workspaceId}
										{itemId}
									/>{/key}
							{:catch}<QueryError
									message={$t('Unable to load organization options.')}
									onRetry={() => (organizeModule = import('./LibraryPreviewOrganize.svelte'))}
								/>{/await}
						{/if}
					</div>
				</section>
				<section class="mt-5 border-t border-surface-300-700 pt-4">
					<h3 class="mb-3 text-sm font-semibold">{$t('Files')}</h3>
					<a class="flex flex-wrap gap-x-4 gap-y-1 text-sm" href={resolve(itemHref('files'))}
						><span>{$t('{count} PDF revisions', { count: item.data.counts.revisions })}</span><span
							>{$t('{count} supplements', { count: item.data.counts.attachments })}</span
						></a
					>
				</section>
			{/if}
		</div>
	</Panel>
</aside>
