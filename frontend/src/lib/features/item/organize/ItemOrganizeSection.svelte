<script lang="ts">
	import { domainLabel } from '#lib/domain-labels.js';
	import { can } from '#lib/authorization/can.js';
	import Badge from '#lib/design/Badge.svelte';
	import ConfirmDialog from '#lib/design/ConfirmDialog.svelte';
	import Panel from '#lib/design/Panel.svelte';
	import { t } from '#lib/i18n.js';
	import type { components } from '#lib/api/schema.js';
	import type { OrganizeView } from '../types';
	import Button from '#lib/design/Button.svelte';

	let { data, busy, error, onToggleProject, onAddTag, onToggleTag, onAddSuggestedTag, onRefresh } =
		$props<{
			data: OrganizeView;
			busy: boolean;
			error: string;
			onToggleProject: (project: OrganizeView['projects'][number]) => Promise<boolean>;
			onAddTag: (event: SubmitEvent) => void;
			onToggleTag: (tagId: string, assigned: boolean) => void;
			onAddSuggestedTag: (name: string) => void;
			onRefresh: () => void;
		}>();

	let tagFilter = $state('');
	let projectFilter = $state('');
	let removeProjectDialogOpen = $state(false);
	let pendingRemoveProject = $state<OrganizeView['projects'][number]>();
	const primaryProjects = $derived(
		data.projects.filter(
			(project: OrganizeView['projects'][number]) =>
				project.assigned || project.is_participating || project.participation === 'workspace'
		)
	);
	const otherOpenProjects = $derived(
		data.projects.filter(
			(project: OrganizeView['projects'][number]) =>
				!project.assigned &&
				!project.is_participating &&
				project.participation === 'open' &&
				project.name.toLocaleLowerCase().includes(projectFilter.toLocaleLowerCase())
		)
	);
	const managedProjects = $derived(
		data.projects.filter(
			(project: OrganizeView['projects'][number]) =>
				!project.assigned && !project.is_participating && project.participation === 'managed'
		)
	);
	const canUseTags = $derived(can(data.authorization, 'tag.use'));
	const canCreateTags = $derived(canUseTags && can(data.authorization, 'tag.create'));
	const canManageProjects = $derived(can(data.authorization, 'project_item.manage'));
	const assignedTags = $derived(
		data.tag_matrix.groups
			.flatMap((group: components['schemas']['TagMatrixGroupView']) => group.tags)
			.filter((tag: components['schemas']['ItemTagView']) =>
				data.tag_matrix.assigned_ids.includes(tag.id)
			)
	);
	const groups = $derived(
		data.tag_matrix.groups
			.map((group: components['schemas']['TagMatrixGroupView']) => ({
				letter: group.letter,
				tags: group.tags.filter((tag: components['schemas']['ItemTagView']) =>
					tag.name.toLocaleLowerCase().includes(tagFilter.toLocaleLowerCase())
				)
			}))
			.filter((group: components['schemas']['TagMatrixGroupView']) => group.tags.length)
	);

	function toggleProject(project: OrganizeView['projects'][number]) {
		if (busy || !canManageProjects) return;
		if (project.assigned) {
			pendingRemoveProject = project;
			removeProjectDialogOpen = true;
		} else void onToggleProject(project);
	}

	async function confirmRemoveProject() {
		if (!pendingRemoveProject || busy || !canManageProjects) return;
		if (await onToggleProject(pendingRemoveProject)) {
			removeProjectDialogOpen = false;
			pendingRemoveProject = undefined;
		}
	}
</script>

{#snippet projectRows(projects: OrganizeView['projects'])}
	<div class="divide-y divide-surface-300-700">
		{#each projects as project (project.id)}
			<div class="flex items-center justify-between gap-3 py-2">
				<strong class="truncate text-sm font-semibold">{project.name}</strong>
				<Button
					variant={project.assigned ? 'tonal' : 'primary'}
					size="sm"
					disabled={busy || !canManageProjects}
					onclick={() => toggleProject(project)}
				>
					{project.assigned ? $t('Remove') : $t('Add')}
				</Button>
			</div>
		{/each}
	</div>
{/snippet}

<div class="grid grid-cols-1 items-start gap-4 xl:grid-cols-[minmax(0,1.75fr)_minmax(19rem,1fr)]">
	<div class="grid grid-cols-1 gap-4">
		<Panel>
			<div class="mb-4 flex flex-wrap items-start justify-between gap-3">
				<div>
					<h2 class="m-0">{$t('Tag matrix')}</h2>
					<p class="m-0 text-sm text-surface-600-400">
						{$t('Browse the complete accessible taxonomy.')}
					</p>
				</div>
				<input
					class="input w-auto min-w-36 field-sm"
					bind:value={tagFilter}
					placeholder={$t('Filter Tags')}
				/>
			</div>
			<div class="grid grid-cols-1 gap-x-6 gap-y-4 sm:grid-cols-2 2xl:grid-cols-3">
				{#each groups as group (group.letter)}
					<div>
						<h3 class="mb-2 text-xs font-bold tracking-[0.12em] text-surface-600-400 uppercase">
							{group.letter}
						</h3>
						<div class="flex flex-wrap gap-1.5">
							{#each group.tags as tag (tag.id)}
								{@const assigned = data.tag_matrix.assigned_ids.includes(tag.id)}
								<Badge
									as="button"
									type="button"
									variant={assigned ? 'primary' : 'surface'}
									class={`cursor-pointer ${assigned ? 'border-primary-700-300' : ''}`}
									disabled={busy || !canUseTags}
									aria-pressed={assigned}
									onclick={() => onToggleTag(tag.id, assigned)}
									>{tag.name}{data.tag_matrix.recommended_ids.includes(tag.id) ? ' ★' : ''}</Badge
								>
							{/each}
						</div>
					</div>
				{/each}
			</div>
			{#if !groups.length}<p class="m-0 text-sm text-surface-600-400">{$t('No tags')}</p>{/if}
		</Panel>
		<Panel>
			<h2 class="m-0 mb-2">{$t('Projects')}</h2>

			{#if primaryProjects.length > 0}
				<p class="text-sm text-surface-600-400">{$t('Assigned, Workspace and Your Projects')}</p>
				{@render projectRows(primaryProjects)}
			{/if}
			{#if data.projects.some((project: OrganizeView['projects'][number]) => !project.assigned && !project.is_participating && project.participation === 'open')}
				<details class="mt-3">
					<summary class="cursor-pointer text-sm font-semibold">{$t('Other open Projects')}</summary
					>
					<input
						class="mt-2 input"
						bind:value={projectFilter}
						aria-label={$t('Search Projects')}
						placeholder={$t('Search Projects')}
					/>
					{@render projectRows(otherOpenProjects)}
					{#if otherOpenProjects.length === 0}<p class="text-sm text-surface-600-400">
							{$t('No matching Projects.')}
						</p>{/if}
				</details>
			{/if}
			{#if managedProjects.length > 0}
				<details class="mt-3">
					<summary class="cursor-pointer text-sm font-semibold">{$t('Managed Projects')}</summary>
					{@render projectRows(managedProjects)}
				</details>
			{/if}
			{#if data.projects.length === 0}<p class="m-0 text-sm text-surface-600-400">
					{$t('No available projects.')}
				</p>{/if}
		</Panel>
	</div>
	<div class="grid grid-cols-1 gap-4">
		<Panel>
			<h2 class="m-0">{$t('Item Tags')}</h2>
			<p class="mt-1 mb-3 text-sm text-surface-600-400">
				{$t('Tags currently assigned to this Item.')}
			</p>
			<div class="flex flex-wrap gap-1.5">
				{#each assignedTags as tag (tag.id)}
					<Badge
						as="button"
						type="button"
						variant="primary"
						class="cursor-pointer"
						disabled={busy || !canUseTags}
						aria-label={$t('Remove {name}', { name: tag.name })}
						onclick={() => onToggleTag(tag.id, true)}
						>{tag.name}<span aria-hidden="true"> ×</span></Badge
					>
				{:else}
					<span class="text-sm text-surface-600-400">{$t('No tags')}</span>
				{/each}
			</div>
			{#if canCreateTags}<form class="mt-3 flex items-center gap-2" onsubmit={onAddTag}>
					<input
						class="input min-w-0 flex-1 field-sm"
						name="name"
						placeholder={$t('New tag')}
						required
					/><Button size="sm" class="shrink-0" disabled={busy}>{$t('Add tag')}</Button>
				</form>{/if}
		</Panel>
		<Panel>
			<div class="flex items-start justify-between gap-3">
				<h2 class="m-0">{$t('Tag Recommendations')}</h2>
				<Button
					size="sm"
					class="shrink-0"
					disabled={busy || !can(data.authorization, 'item.update')}
					onclick={onRefresh}>{$t('Refresh')}</Button
				>
			</div>
			<p class="mt-1 mb-3 text-sm text-surface-600-400">
				{$t('Suggestions derived from metadata and the latest ready PDF.')}
			</p>
			{#if data.tag_matrix.recommendation_error}
				<p class="text-error-700-300">{data.tag_matrix.recommendation_error}</p>
			{/if}
			<div class="flex flex-wrap gap-1.5">
				{#each data.tag_matrix.suggested_names as name (name)}
					<Badge
						as="button"
						type="button"
						variant="warning"
						class="cursor-pointer border border-warning-700-300/30"
						disabled={busy || !canCreateTags}
						onclick={() => onAddSuggestedTag(name)}>+ {name}</Badge
					>
				{:else}
					<span class="text-sm text-surface-600-400">{$t('No new Tag suggestions.')}</span>
				{/each}
			</div>
			<div
				class="mt-3 flex items-center gap-2 border-t border-surface-300-700 pt-3 text-xs text-surface-600-400"
			>
				{$t('State')}
				<Badge>{$t(domainLabel(data.tag_matrix.recommendation_state))}</Badge>
			</div>
		</Panel>
	</div>
</div>

<ConfirmDialog
	bind:open={removeProjectDialogOpen}
	title={$t('Remove Item from Project?')}
	body={$t(
		'Removing this Item from {name} permanently deletes all of its Project Annotations and Replies in this Project. This cannot be undone. The Item, its files, private Annotations and other Projects are preserved.',
		{ name: pendingRemoveProject?.name ?? '' }
	) + (removeProjectDialogOpen && error ? ` ${error}` : '')}
	confirmLabel={$t('Remove from Project')}
	{busy}
	onConfirm={() => void confirmRemoveProject()}
/>
