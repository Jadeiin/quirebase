<script lang="ts">
	import { createMutation, createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { can } from '#lib/authorization/can.js';
	import { apiErrorMessage } from '#lib/api/errors.js';
	import Badge from '#lib/design/Badge.svelte';
	import Button from '#lib/design/Button.svelte';
	import ConfirmDialog from '#lib/design/ConfirmDialog.svelte';
	import Notice from '#lib/design/Notice.svelte';
	import QueryError from '#lib/design/QueryError.svelte';
	import SearchSelect from '#lib/design/SearchSelect.svelte';
	import {
		projectAssignmentMutationOptions,
		suggestedTagMutationOptions,
		toggleTagMutationOptions
	} from '#lib/features/item/organize/mutations.js';
	import { itemOrganizeQuery } from '#lib/features/item/queries.js';
	import type { OrganizeView } from '#lib/features/item/types.js';
	import { t } from '#lib/i18n.js';

	// The caller keys this controller by Workspace and Item so pending operations
	// and their feedback remain attached to the Item submitted by the user.
	let { workspaceId, itemId }: { workspaceId: string; itemId: string } = $props();
	const queryClient = useQueryClient();
	const organize = createQuery(() => itemOrganizeQuery(workspaceId, itemId));
	const tagAssignment = createMutation(() =>
		toggleTagMutationOptions(workspaceId, itemId, queryClient)
	);
	const newTag = createMutation(() =>
		suggestedTagMutationOptions(workspaceId, itemId, queryClient)
	);
	const projectAssignment = createMutation(() =>
		projectAssignmentMutationOptions(workspaceId, itemId, queryClient)
	);
	const busy = $derived(tagAssignment.isPending || newTag.isPending || projectAssignment.isPending);
	const canUseTags = $derived(can(organize.data?.authorization, 'tag.use'));
	const canCreateTags = $derived(canUseTags && can(organize.data?.authorization, 'tag.create'));
	const canManageProjects = $derived(can(organize.data?.authorization, 'project_item.manage'));
	const tags = $derived(organize.data?.tag_matrix.groups.flatMap((group) => group.tags) ?? []);
	const assignedTags = $derived(
		tags.filter((tag) => organize.data?.tag_matrix.assigned_ids.includes(tag.id))
	);
	const assignedProjects = $derived(
		organize.data?.projects.filter((project) => project.assigned) ?? []
	);
	let tagName = $state('');
	let projectId = $state('');
	let mutationError = $state('');
	let saved = $state(false);
	let retryOperation = $state<(() => Promise<unknown>) | undefined>();
	let removeProjectOpen = $state(false);
	let pendingProject = $state<OrganizeView['projects'][number]>();
	let heading: HTMLHeadingElement;
	const availableTags = $derived(
		tags.filter((tag) => !organize.data?.tag_matrix.assigned_ids.includes(tag.id))
	);
	const availableProjects = $derived(
		organize.data?.projects.filter((project) => !project.assigned) ?? []
	);
	const selectedProject = $derived(availableProjects.find((project) => project.id === projectId));
	const selectedTag = $derived(availableTags.find((tag) => tag.name === tagName.trim()));
	const tagAlreadyAssigned = $derived(assignedTags.some((tag) => tag.name === tagName.trim()));
	const canAddTag = $derived(
		Boolean(tagName.trim()) &&
			!tagAlreadyAssigned &&
			canUseTags &&
			(Boolean(selectedTag) || canCreateTags)
	);

	async function run(operation: () => Promise<unknown>, retry = true) {
		if (busy) return false;
		const trigger = document.activeElement;
		mutationError = '';
		saved = false;
		retryOperation = retry ? operation : undefined;
		try {
			await operation();
			saved = true;
			retryOperation = undefined;
			if (
				trigger instanceof HTMLElement &&
				!trigger.isConnected &&
				document.activeElement === document.body &&
				heading?.isConnected
			)
				heading.focus();
			return true;
		} catch (error) {
			mutationError = apiErrorMessage(error, $t('Unable to save changes'));
			return false;
		}
	}

	function addTag(event: SubmitEvent) {
		event.preventDefault();
		if (!canAddTag) return;
		const name = tagName.trim();
		const existing = selectedTag;
		void run(async () => {
			if (existing) await tagAssignment.mutateAsync({ tagId: existing.id, assigned: false });
			else await newTag.mutateAsync({ name });
			if (tagName.trim() === name) tagName = '';
		});
	}

	function addProject(event: SubmitEvent) {
		event.preventDefault();
		const project = selectedProject;
		if (!project || !canManageProjects) return;
		void run(async () => {
			await projectAssignment.mutateAsync({ project });
			if (projectId === project.id) projectId = '';
		});
	}

	function removeProject(project: OrganizeView['projects'][number]) {
		pendingProject = project;
		mutationError = '';
		removeProjectOpen = true;
	}

	async function confirmRemoveProject() {
		const project = pendingProject;
		if (!project || !canManageProjects) return;
		if (await run(() => projectAssignment.mutateAsync({ project }), false)) {
			removeProjectOpen = false;
			pendingProject = undefined;
		}
	}
</script>

<section aria-labelledby="preview-organize-heading" aria-busy={busy} class="mt-4">
	<h3 id="preview-organize-heading" class="sr-only" tabindex="-1" bind:this={heading}>
		{$t('Organize this Item')}
	</h3>
	{#if organize.isPending}
		<p role="status" class="text-sm text-surface-600-400">{$t('Loading organization options…')}</p>
	{:else if organize.isError}
		<QueryError
			message={apiErrorMessage(organize.error, $t('Unable to load organization options.'))}
			busy={organize.isFetching}
			onRetry={() => void organize.refetch()}
		/>
	{:else if organize.data}
		{#if mutationError && !removeProjectOpen}
			<Notice as="div" variant="error" class="mb-3 text-sm">
				{mutationError}
				{#if retryOperation}
					<Button
						size="sm"
						class="mt-2"
						disabled={busy}
						onclick={() => retryOperation && void run(retryOperation)}>{$t('Retry')}</Button
					>
				{/if}
			</Notice>
		{/if}
		{#if saved}<p role="status" class="mb-3 text-sm text-success-700-300">
				{$t('Item organization updated')}
			</p>{/if}
		<div>
			<h4 class="mb-2 text-sm font-semibold">{$t('Tags')}</h4>
			<div class="flex flex-wrap gap-1.5">
				{#each assignedTags as tag (tag.id)}
					<Badge
						as="button"
						type="button"
						variant="primary"
						class="max-w-full whitespace-normal"
						disabled={busy || !canUseTags}
						aria-label={$t('Remove {name}', { name: tag.name })}
						onclick={() =>
							void run(() => tagAssignment.mutateAsync({ tagId: tag.id, assigned: true }))}
					>
						<span class="min-w-0 break-words">{tag.name}</span><span aria-hidden="true"> ×</span>
					</Badge>
				{:else}<span class="text-sm text-surface-600-400">{$t('No tags')}</span>{/each}
			</div>
			{#if canUseTags}
				<form class="mt-3 flex items-end gap-2" onsubmit={addTag}>
					<SearchSelect
						bind:value={tagName}
						label={$t('Add a Tag to this Item')}
						class="flex-1"
						disabled={busy}
						options={availableTags.map((tag) => ({ value: tag.name, label: tag.name }))}
						allowCustomValue={canCreateTags}
					/>
					<Button type="submit" disabled={busy || !canAddTag}>{$t('Add tag')}</Button>
				</form>
			{/if}
		</div>
		<div class="mt-5 border-t border-surface-300-700 pt-4">
			<h4 class="mb-2 text-sm font-semibold">{$t('Projects')}</h4>
			<div class="grid grid-cols-1 gap-2">
				{#each assignedProjects as project (project.id)}
					<div class="flex min-w-0 items-center justify-between gap-2">
						<span class="min-w-0 text-sm break-words">{project.name}</span>
						<Button
							size="sm"
							disabled={busy || !canManageProjects}
							aria-label={$t('Remove from {name}', { name: project.name })}
							onclick={() => removeProject(project)}>{$t('Remove')}</Button
						>
					</div>
				{:else}<span class="text-sm text-surface-600-400">{$t('No assigned Projects')}</span>{/each}
			</div>
			{#if canManageProjects}
				<form class="mt-3 flex items-end gap-2" onsubmit={addProject}>
					<SearchSelect
						bind:value={projectId}
						label={$t('Add to a Project')}
						class="flex-1"
						disabled={busy}
						options={availableProjects.map((project) => ({
							value: project.id,
							label: project.name
						}))}
					/>
					<Button type="submit" disabled={busy || !selectedProject}>{$t('Add')}</Button>
				</form>
			{/if}
		</div>
	{/if}
</section>

<ConfirmDialog
	bind:open={removeProjectOpen}
	title={$t('Remove Item from Project?')}
	body={$t(
		'Removing this Item from {name} permanently deletes all of its Project Annotations and Replies in this Project. This cannot be undone. The Item, its files, private Annotations and other Projects are preserved.',
		{ name: pendingProject?.name ?? '' }
	)}
	confirmLabel={$t('Remove from Project')}
	{busy}
	error={mutationError}
	finalFocusEl={() => (heading?.isConnected ? heading : null)}
	onConfirm={() => void confirmRemoveProject()}
/>
