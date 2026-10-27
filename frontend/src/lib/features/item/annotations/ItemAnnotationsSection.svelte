<script lang="ts">
	import { resolve } from '$app/paths';
	import { page as appPage } from '$app/state';
	import { createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { ApiError } from '#lib/api/client.js';
	import { apiErrorMessage } from '#lib/api/errors.js';
	import type { components } from '#lib/api/schema.js';
	import { can } from '#lib/authorization/can.js';
	import ConfirmDialog from '#lib/design/ConfirmDialog.svelte';
	import Notice from '#lib/design/Notice.svelte';
	import { domainLabel } from '#lib/domain-labels.js';
	import Panel from '#lib/design/Panel.svelte';
	import Pagination from '#lib/design/Pagination.svelte';
	import SectionHeader from '#lib/design/SectionHeader.svelte';
	import { invalidateItemAnnotations } from '#lib/query/invalidation.js';
	import { msg, plural, t } from 'lingui-for-svelte/macro';
	import type { MessageDescriptor } from '@lingui/core';
	import { getWorkspaceContext } from '#lib/workspaces/context.svelte.js';
	import { libraryItemHref, readLibraryReturnTo } from '#lib/features/library/return-context.js';
	import { itemAnnotationsQuery } from '../queries';
	import Button from '#lib/design/Button.svelte';
	import ItemRow from '#lib/design/ItemRow.svelte';

	type AnnotationModerationAction = components['schemas']['AnnotationModerationRequest']['action'];

	let { itemId }: { itemId: string } = $props();
	const { workspaceId } = getWorkspaceContext();
	const returnTo = $derived(readLibraryReturnTo(workspaceId, appPage.url.searchParams));
	const workspace = getWorkspaceContext();
	const queryClient = useQueryClient();
	let revision = $state('all');
	let source = $state('all');
	let page = $state(1);
	let pageSize = $state(50);
	let moderationError = $state('');
	let moderating = $state('');
	let confirmDeleteOpen = $state(false);
	let pendingDelete = $state<components['schemas']['AnnotationView']>();
	const annotations = createQuery(() =>
		itemAnnotationsQuery(workspaceId, itemId, revision, source, page, true, pageSize)
	);
	const projects = $derived(annotations.data?.projects ?? []);
	const revisions = $derived(annotations.data?.revisions ?? []);
	const displayed = $derived(annotations.data?.annotations ?? []);
	const pageCount = $derived(
		Math.max(1, Math.ceil((annotations.data?.total ?? 0) / (annotations.data?.per_page ?? 50)))
	);
	const workspaceRevisionId = $derived(revision === 'all' ? revisions[0]?.id : revision);
	const moderationLabels = {
		hide: msg`Hide`,
		archive: msg`Archive`,
		restore: msg`Restore`,
		lock: msg`Lock`,
		unlock: msg`Unlock`,
		delete: msg`Delete`
	} as const satisfies Record<AnnotationModerationAction, MessageDescriptor>;
	const moderationActions = Object.keys(moderationLabels) as AnnotationModerationAction[];

	function annotationCanModerate(
		annotation: components['schemas']['AnnotationView'],
		action: AnnotationModerationAction
	): boolean {
		return !annotation.mine && can(annotation.authorization, `project_annotation.${action}`);
	}

	async function moderate(
		annotation: components['schemas']['AnnotationView'],
		action: AnnotationModerationAction
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
			await invalidateItemAnnotations(queryClient, workspaceId, itemId);
		} catch (reason) {
			if (reason instanceof ApiError && reason.status === 409) {
				await invalidateItemAnnotations(queryClient, workspaceId, itemId);
				moderationError = $t`This Annotation changed. Review the latest version and try again.`;
			} else moderationError = apiErrorMessage(reason, $t`Unable to moderate Annotation`);
		} finally {
			moderating = '';
		}
	}

	function requestDelete(annotation: components['schemas']['AnnotationView']) {
		pendingDelete = annotation;
		confirmDeleteOpen = true;
	}

	function confirmDelete() {
		const annotation = pendingDelete;
		pendingDelete = undefined;
		confirmDeleteOpen = false;
		if (annotation) void moderate(annotation, 'delete');
	}
</script>

<Panel class="mt-4">
	<SectionHeader>
		<h2>{$t`Annotations`}</h2>
		{#snippet actions()}
			<label class="flex items-center gap-2 text-sm text-surface-700-300"
				>{$t`Annotation source`}
				<select class="input w-auto min-w-36" bind:value={source} onchange={() => (page = 1)}>
					<option value="all">{$t`All sources`}</option>
					<option value="private">{$t`Private annotations`}</option>
					{#each projects as project (project.id)}<option value={project.id}>{project.name}</option
						>{/each}
				</select>
			</label>
			{#if revisions.length > 1}
				<label class="flex items-center gap-2 text-sm text-surface-700-300"
					>{$t`PDF revision`}<select
						class="input w-auto min-w-36"
						bind:value={revision}
						onchange={() => (page = 1)}
						><option value="all">{$t`All revisions`}</option
						>{#each revisions as item (item.id)}<option value={item.id}>{item.original_name}</option
							>{/each}</select
					></label
				>
			{/if}
		{/snippet}
	</SectionHeader>
	{#if annotations.isPending}
		<p class="text-surface-600-400">{$t`Loading annotations…`}</p>
	{:else if annotations.isError}
		<p class="text-error-700-300">{$t`Unable to load annotations.`}</p>
	{:else if revisions.length === 0}
		<p class="text-surface-600-400">{$t`Add a PDF revision to begin annotating.`}</p>
	{:else}
		{#if moderationError}<Notice variant="error">{moderationError}</Notice>{/if}
		{#each displayed as annotation (annotation.id)}
			<ItemRow class="min-w-0 grid-cols-1 wrap-anywhere">
				<div class="flex flex-wrap justify-between gap-2">
					<strong
						>{$t(domainLabel(annotation.kind))} · {$t`page`}
						{annotation.page_index + 1}</strong
					><a
						class="text-sm font-semibold text-primary-700-300 no-underline"
						href={resolve(
							libraryItemHref(
								workspaceId,
								itemId,
								`pdf/${annotation.revision_id}${annotation.project_id ? `?${new URLSearchParams({ project_id: annotation.project_id })}` : ''}`,
								returnTo
							)
						)}>{$t`Open PDF`}</a
					>
				</div>
				<span>{annotation.body ?? annotation.selected_text ?? $t`No note text`}</span><span
					class="text-surface-600-400"
					>{annotation.scope === 'private' ? $t`Private annotations` : annotation.project_name} · {annotation.author_display_name}
					· {annotation.revision_name} ·
					{$plural(
						{ count: (annotation.replies ?? []).length },
						{ one: '# reply', other: '# replies' }
					)}</span
				>
				{#if moderationActions.some((action) => annotationCanModerate(annotation, action))}<div
						class="flex flex-wrap gap-2 border-t border-surface-300-700 pt-2"
						aria-label={$t`Moderator actions`}
					>
						{#each moderationActions.filter( (action) => annotationCanModerate(annotation, action) ) as action (action)}
							{#if action === 'delete'}<Button
									size="sm"
									variant="danger"
									disabled={moderating !== ''}
									onclick={() => requestDelete(annotation)}>{$t(moderationLabels[action])}</Button
								>{:else}<Button
									size="sm"
									variant="tonal"
									disabled={moderating !== ''}
									onclick={() => void moderate(annotation, action)}
									>{$t(moderationLabels[action])}</Button
								>{/if}
						{/each}
					</div>{/if}
			</ItemRow>
		{:else}
			<p class="text-surface-600-400">{$t`No annotations.`}</p>
		{/each}
		<Button
			as="a"
			variant="filled"
			href={resolve(
				libraryItemHref(
					workspaceId,
					itemId,
					`pdf/${workspaceRevisionId}${source !== 'all' && source !== 'private' ? `?${new URLSearchParams({ project_id: source })}` : ''}`,
					returnTo
				)
			)}>{$t`Open annotation workspace`}</Button
		>
	{/if}
	<Pagination
		{page}
		{pageCount}
		{pageSize}
		total={annotations.data?.total ?? 0}
		onPageSize={(size) => {
			pageSize = size;
			page = 1;
		}}
		label={$t`Annotation pages`}
		busy={annotations.isFetching}
		class="mt-4"
		onPage={(next) => (page = next)}
	/>
</Panel>
<ConfirmDialog
	bind:open={confirmDeleteOpen}
	title={$t`Delete`}
	body={$t`This cannot be undone.`}
	confirmLabel={$t`Delete`}
	busy={moderating !== ''}
	onConfirm={confirmDelete}
/>
