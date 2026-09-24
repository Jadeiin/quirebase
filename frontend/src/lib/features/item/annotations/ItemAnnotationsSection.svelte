<script lang="ts">
	import { resolve } from '$app/paths';
	import { createQuery } from '@tanstack/svelte-query';
	import { ApiError } from '$lib/api/client';
	import { apiErrorMessage } from '$lib/api/errors';
	import type { components } from '$lib/api/schema';
	import Notice from '$lib/design/Notice.svelte';
	import { domainLabel } from '$lib/domain-labels';
	import Panel from '$lib/design/Panel.svelte';
	import Pagination from '$lib/design/Pagination.svelte';
	import SectionHeader from '$lib/design/SectionHeader.svelte';
	import { t } from '$lib/i18n';
	import { getWorkspaceContext } from '$lib/workspaces/context.svelte';
	import { workspaceHref } from '$lib/workspaces/href';
	import { itemAnnotationsReviewQuery } from '../queries';
	import Button from '$lib/design/Button.svelte';
	import ItemRow from '$lib/design/ItemRow.svelte';

	let { itemId } = $props<{ itemId: string }>();
	const { workspaceId } = getWorkspaceContext();
	const workspace = getWorkspaceContext();
	let revision = $state('all');
	let page = $state(1);
	let moderationError = $state('');
	let moderating = $state('');
	const annotations = createQuery(() =>
		itemAnnotationsReviewQuery(workspaceId, itemId, revision, page, true)
	);
	const revisions = $derived(annotations.data?.revisions ?? []);
	const displayed = $derived(annotations.data?.annotations ?? []);
	const pageCount = $derived(
		Math.max(1, Math.ceil((annotations.data?.total ?? 0) / (annotations.data?.per_page ?? 50)))
	);
	const workspaceRevisionId = $derived(revision === 'all' ? revisions[0]?.id : revision);

	async function moderate(
		annotation: components['schemas']['AnnotationReviewAnnotationView'],
		action: 'hide' | 'archive' | 'restore' | 'lock' | 'unlock'
	) {
		moderating = annotation.id;
		moderationError = '';
		try {
			await workspace.api.request(
				'POST',
				'/workspaces/{workspace_id}/items/{item_id}/annotations/{annotation_id}/moderation',
				{
					params: { path: { item_id: itemId, annotation_id: annotation.id } },
					body: { action, version: annotation.version }
				}
			);
			await annotations.refetch();
		} catch (reason) {
			if (reason instanceof ApiError && reason.status === 409) {
				await annotations.refetch();
				moderationError =
					'This Annotation changed since it was loaded. Latest state refreshed; review it and explicitly retry if the action is still appropriate.';
			} else moderationError = apiErrorMessage(reason, 'Unable to moderate Annotation');
		} finally {
			moderating = '';
		}
	}
</script>

<Panel class="mt-4">
	<SectionHeader>
		<h2>{$t('Annotations')}</h2>
		{#snippet actions()}
			{#if revisions.length > 1}
				<label class="flex items-center gap-2 text-sm text-surface-700-300"
					>{$t('PDF revision')}<select
						class="input w-auto min-w-36"
						bind:value={revision}
						onchange={() => (page = 1)}
						><option value="all">{$t('All revisions')}</option
						>{#each revisions as item (item.id)}<option value={item.id}>{item.original_name}</option
							>{/each}</select
					></label
				>
			{/if}
		{/snippet}
	</SectionHeader>
	{#if annotations.isPending}
		<p class="text-surface-600-400">{$t('Loading annotations…')}</p>
	{:else if annotations.isError}
		<p class="text-error-700-300">{$t('Unable to load annotations.')}</p>
	{:else if revisions.length === 0}
		<p class="text-surface-600-400">{$t('Add a PDF revision to begin annotating.')}</p>
	{:else}
		{#if moderationError}<Notice variant="error">{moderationError}</Notice>{/if}
		{#each displayed as annotation (annotation.id)}
			<ItemRow>
				<div class="flex flex-wrap justify-between gap-2">
					<strong
						>{$t(domainLabel(annotation.kind))} · {$t('page')}
						{annotation.page_index + 1}</strong
					><a
						class="text-sm font-semibold text-primary-700-300 no-underline"
						href={resolve(
							workspaceHref(workspaceId, `item/${itemId}/pdf/${annotation.revision_id}`)
						)}>{$t('Open PDF')}</a
					>
				</div>
				<span>{annotation.body ?? annotation.selected_text ?? $t('No note text')}</span><span
					class="text-surface-600-400"
					>{annotation.author_display_name} · {annotation.revision_name} ·
					{$t('{count, plural, one {# reply} other {# replies}}', {
						count: (annotation.replies ?? []).length
					})}</span
				>
				{#if annotation.allowed_actions.some( (action) => ['hide', 'archive', 'restore', 'lock', 'unlock'].includes(action) )}<div
						class="flex flex-wrap gap-2 border-t border-surface-300-700 pt-2"
						aria-label={$t('Moderator actions')}
					>
						{#each (['hide', 'archive', 'restore', 'lock', 'unlock'] as const).filter( (action) => annotation.allowed_actions.includes(action) ) as action (action)}<Button
								size="sm"
								variant="tonal"
								disabled={moderating !== ''}
								onclick={() => void moderate(annotation, action)}>{action}</Button
							>{/each}
					</div>{/if}
			</ItemRow>
		{:else}
			<p class="text-surface-600-400">{$t('No annotations.')}</p>
		{/each}
		<Button
			as="a"
			variant="filled"
			href={resolve(workspaceHref(workspaceId, `item/${itemId}/pdf/${workspaceRevisionId}`))}
			>{$t('Open annotation workspace')}</Button
		>
	{/if}
	{#if pageCount > 1}
		<Pagination
			{page}
			{pageCount}
			label={$t('Annotation pages')}
			busy={annotations.isFetching}
			class="mt-4"
			onPage={(next) => (page = next)}
		/>
	{/if}
</Panel>
