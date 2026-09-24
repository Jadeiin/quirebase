<script lang="ts">
	import { domainLabel } from '$lib/domain-labels';
	import Badge from '$lib/design/Badge.svelte';
	import Panel from '$lib/design/Panel.svelte';
	import { t } from '$lib/i18n';
	import type { components } from '$lib/api/schema';
	import type { OrganizeView } from '../types';
	import Button from '$lib/design/Button.svelte';

	let { data, busy, onToggleProject, onAddTag, onToggleTag, onAddSuggestedTag, onRefresh } =
		$props<{
			data: OrganizeView;
			busy: boolean;
			onToggleProject: (project: OrganizeView['projects'][number]) => void;
			onAddTag: (event: SubmitEvent) => void;
			onToggleTag: (tagId: string, assigned: boolean) => void;
			onAddSuggestedTag: (name: string) => void;
			onRefresh: () => void;
		}>();

	let tagFilter = $state('');
	const canEdit = $derived(data.allowed_actions.edit);
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
</script>

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
					class="input w-auto min-w-36 border border-surface-300-700 field-sm"
					bind:value={tagFilter}
					placeholder={$t('Filter Tags')}
				/>
			</div>
			<div class="gap-x-6 sm:columns-2 2xl:columns-3">
				{#each groups as group (group.letter)}
					<div class="mb-4 break-inside-avoid last:mb-0">
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
									class={`cursor-pointer border ${assigned ? 'border-primary-700-300' : 'border-surface-300-700'}`}
									disabled={busy || !canEdit}
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
			<div class="divide-y divide-surface-300-700">
				{#each data.projects as project (project.id)}
					<div class="flex items-center justify-between gap-3 py-2">
						<div class="flex min-w-0 items-center gap-2">
							<strong class="truncate text-sm font-semibold">{project.name}</strong>
							<Badge class="shrink-0 border border-surface-300-700"
								>{$t(domainLabel(project.role))}</Badge
							>
						</div>
						<Button
							variant={project.assigned ? 'tonal' : 'primary'}
							size="sm"
							class={`shrink-0 border ${project.assigned ? 'border-surface-300-700' : 'border-primary-700-300/30'}`}
							disabled={busy || !canEdit}
							onclick={() => onToggleProject(project)}
							>{project.assigned ? $t('Remove') : $t('Add')}</Button
						>
					</div>
				{:else}
					<p class="m-0 text-sm text-surface-600-400">{$t('No available projects.')}</p>
				{/each}
			</div>
		</Panel>
	</div>
	<div class="grid grid-cols-1 gap-4">
		<Panel>
			<h2 class="m-0">{$t('Item Tags')}</h2>
			<p class="mt-1 mb-3 text-sm text-surface-600-400">
				{$t('Tags currently assigned to this Item.')}
			</p>
			<div class="flex flex-wrap gap-1.5">
				{#each data.tags as tag (tag.id)}
					<Badge
						as="button"
						type="button"
						variant="primary"
						class="cursor-pointer border border-primary-700-300/20"
						disabled={busy || !canEdit}
						onclick={() => onToggleTag(tag.id, true)}>{tag.name} ×</Badge
					>
				{:else}
					<span class="text-sm text-surface-600-400">{$t('No tags')}</span>
				{/each}
			</div>
			<form class="mt-3 flex items-center gap-2" onsubmit={onAddTag}>
				<input
					class="input min-w-0 flex-1 border border-surface-300-700 field-sm"
					name="name"
					placeholder={$t('New tag')}
					required
				/><Button
					size="sm"
					class="shrink-0 border border-surface-300-700"
					disabled={busy || !canEdit}>{$t('Add tag')}</Button
				>
			</form>
		</Panel>
		<Panel>
			<div class="flex items-start justify-between gap-3">
				<h2 class="m-0">{$t('Tag Recommendations')}</h2>
				<Button
					size="sm"
					class="shrink-0 border border-surface-300-700"
					disabled={busy || !canEdit}
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
						disabled={busy || !canEdit}
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
				<Badge class="border border-surface-300-700"
					>{$t(domainLabel(data.tag_matrix.recommendation_state))}</Badge
				>
			</div>
		</Panel>
	</div>
</div>
