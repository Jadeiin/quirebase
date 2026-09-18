<script lang="ts">
	import { resolve } from '$app/paths';
	import { createQuery } from '@tanstack/svelte-query';
	import { domainLabel } from '$lib/domain-labels';
	import { t } from '$lib/i18n';
	import { itemAnnotationsReviewQuery } from './queries';

	let { itemId } = $props<{ itemId: string }>();
	let revision = $state('all');
	let page = $state(1);
	const annotations = createQuery(() => itemAnnotationsReviewQuery(itemId, revision, page, true));
	const revisions = $derived(annotations.data?.revisions ?? []);
	const displayed = $derived(annotations.data?.annotations ?? []);
	const pageCount = $derived(
		Math.max(1, Math.ceil((annotations.data?.total ?? 0) / (annotations.data?.per_page ?? 50)))
	);
	const workspaceRevisionId = $derived(revision === 'all' ? revisions[0]?.id : revision);
</script>

<section class="list-panel card border border-surface-300-700 bg-surface-50-950 p-5 shadow-sm">
	<div class="workspace-header">
		<h2>{$t('Annotations')}</h2>
		{#if revisions.length > 1}
			<label class="flex items-center gap-2 text-sm text-surface-700-300"
				>{$t('PDF revision')}<select
					class="compact input"
					bind:value={revision}
					onchange={() => (page = 1)}
					><option value="all">{$t('All revisions')}</option
					>{#each revisions as item (item.id)}<option value={item.id}>{item.original_name}</option
						>{/each}</select
				></label
			>
		{/if}
	</div>
	{#if annotations.isPending}
		<p class="text-surface-600-400">{$t('Loading annotations…')}</p>
	{:else if annotations.isError}
		<p class="text-error-700-300">{$t('Unable to load annotations.')}</p>
	{:else if revisions.length === 0}
		<p class="text-surface-600-400">{$t('Add a PDF revision to begin annotating.')}</p>
	{:else}
		{#each displayed as annotation (annotation.id)}
			<div class="item-row">
				<div class="toolbar justify-between">
					<strong
						>{$t(domainLabel(annotation.kind))} · {$t('page')}
						{annotation.page_index + 1}</strong
					><a
						class="text-sm font-semibold text-primary-700-300 no-underline"
						href={resolve('/(app)/item/[itemId]/pdf/[revisionId]', {
							itemId,
							revisionId: annotation.revision_id
						})}>{$t('Open')}</a
					>
				</div>
				<span>{annotation.body ?? annotation.selected_text ?? $t('No note text')}</span><span
					class="text-surface-600-400"
					>{annotation.author_display_name} · {annotation.revision_name} · {(
						annotation.replies ?? []
					).length}
					{$t('replies')}</span
				>
			</div>
		{:else}
			<p class="text-surface-600-400">{$t('No annotations.')}</p>
		{/each}
		<a
			class="btn preset-filled-primary-700-300 font-semibold"
			href={resolve('/(app)/item/[itemId]/pdf/[revisionId]', {
				itemId,
				revisionId: workspaceRevisionId
			})}>{$t('Open annotation workspace')}</a
		>
	{/if}
	{#if pageCount > 1}
		<nav class="pagination mt-4" aria-label={$t('Annotation pages')}>
			<button
				class="btn preset-tonal-surface font-semibold"
				disabled={page <= 1 || annotations.isFetching}
				onclick={() => (page -= 1)}>{$t('Previous')}</button
			>
			<span>{$t('Page')} {page} / {pageCount}</span>
			<button
				class="btn preset-tonal-surface font-semibold"
				disabled={page >= pageCount || annotations.isFetching}
				onclick={() => (page += 1)}>{$t('Next')}</button
			>
		</nav>
	{/if}
</section>
