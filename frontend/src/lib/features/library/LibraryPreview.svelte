<script lang="ts">
	import { resolve } from '$app/paths';
	import { onMount } from 'svelte';
	import { createQuery } from '@tanstack/svelte-query';
	import { itemOverviewQuery } from '#lib/features/item/queries.js';
	import { apiErrorMessage } from '#lib/api/errors.js';
	import Button from '#lib/design/Button.svelte';
	import Icon from '#lib/design/Icon.svelte';
	import Panel from '#lib/design/Panel.svelte';
	import QueryError from '#lib/design/QueryError.svelte';
	import RichText from '#lib/design/RichText.svelte';
	import { t } from '#lib/i18n.js';
	import { workspaceHref } from '#lib/workspaces/href.js';
	import { libraryHref } from './filters';
	let {
		workspaceId,
		itemId,
		onClose,
		onReady
	}: {
		workspaceId: string;
		itemId: string;
		onClose: () => void;
		onReady: (heading: HTMLHeadingElement) => void;
	} = $props();
	const item = createQuery(() => itemOverviewQuery(workspaceId, itemId));
	let heading: HTMLHeadingElement;
	onMount(() => onReady(heading));
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
>
	<Panel padding="none">
		<header
			class="flex items-center justify-between gap-2 border-b border-surface-300-700 px-4 py-3"
		>
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
					disabled={item.isFetching}
					aria-label={$t('Refresh preview')}
					onclick={() => void item.refetch()}><Icon name="rotate" size={16} /></Button
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
				<p class="mb-4 text-sm text-surface-600-400">{item.data.metadata.date_published || '—'}</p>
				<Button as="a" variant="filled" href={resolve(workspaceHref(workspaceId, `item/${itemId}`))}
					>{$t('Open full details')}</Button
				>
				<section class="mt-6 border-t border-surface-300-700 pt-4">
					<h3 class="mb-2 text-sm font-semibold">{$t('Abstract')}</h3>
					<div class="text-sm leading-7 break-words text-surface-700-300">
						{#if item.data.metadata.description}<RichText
								html={item.data.metadata.description}
							/>{:else}<p class="m-0 text-surface-600-400">{$t('No abstract available.')}</p>{/if}
					</div>
				</section>
				<section class="mt-5 border-t border-surface-300-700 pt-4">
					<h3 class="mb-3 text-sm font-semibold">{$t('Tags')}</h3>
					<div class="flex flex-wrap gap-2">
						{#each item.data.tags as tag (tag.id)}<a
								class="max-w-full rounded-full bg-primary-50-950 px-2.5 py-1 text-xs font-semibold break-words text-primary-800-200"
								href={resolve(libraryHref(workspaceId, { tag: tag.id }))}>{tag.name}</a
							>{:else}<span class="text-sm text-surface-600-400">{$t('No tags')}</span>{/each}
					</div>
				</section>
				<section class="mt-5 border-t border-surface-300-700 pt-4">
					<h3 class="mb-3 text-sm font-semibold">{$t('Files')}</h3>
					<a
						class="flex flex-wrap gap-x-4 gap-y-1 text-sm"
						href={resolve(workspaceHref(workspaceId, `item/${itemId}/files`))}
						><span>{$t('{count} PDF revisions', { count: item.data.counts.revisions })}</span><span
							>{$t('{count} supplements', { count: item.data.counts.attachments })}</span
						></a
					>
					{#if item.data.latest_revision_id}<a
							class="mt-3 inline-flex items-center gap-2 text-sm font-semibold"
							href={resolve(
								workspaceHref(workspaceId, `item/${itemId}/pdf/${item.data.latest_revision_id}`)
							)}><Icon name="file" size={16} />{$t('Read PDF')}</a
						>{/if}
				</section>
			{/if}
		</div>
	</Panel>
</aside>
