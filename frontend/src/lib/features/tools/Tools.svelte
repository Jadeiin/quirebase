<script lang="ts">
	import TagSelect from '#lib/features/tags/TagSelect.svelte';
	import LoadingState from '#lib/design/LoadingState.svelte';
	import { resolve } from '$app/paths';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { tick } from 'svelte';
	import { createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { SegmentedControl, Tabs } from '@skeletonlabs/skeleton-svelte';
	import { ApiError } from '#lib/api/client.js';
	import { apiErrorMessage } from '#lib/api/errors.js';
	import { can, type AuthorizationDecisionSet } from '#lib/authorization/can.js';
	import ConfirmDialog from '#lib/design/ConfirmDialog.svelte';
	import Notice from '#lib/design/Notice.svelte';
	import QueryError from '#lib/design/QueryError.svelte';
	import Panel from '#lib/design/Panel.svelte';
	import Pagination from '#lib/design/Pagination.svelte';
	import PromptDialog from '#lib/design/PromptDialog.svelte';
	import RichText from '#lib/design/RichText.svelte';
	import SectionHeader from '#lib/design/SectionHeader.svelte';
	import { tagsQuery } from '#lib/features/tags/queries.js';
	import { citationStylesQuery, duplicateScanQuery } from '#lib/features/tools/queries.js';
	import {
		invalidateCitationStyles,
		invalidateLibrary,
		invalidateTags
	} from '#lib/query/invalidation.js';
	import { t } from '#lib/i18n.js';
	import Button from '#lib/design/Button.svelte';
	import ItemRow from '#lib/design/ItemRow.svelte';
	import { getWorkspaceContext } from '#lib/workspaces/context.svelte.js';
	import { workspaceHref } from '#lib/workspaces/href.js';
	import { createUrlDraft } from '#lib/navigation/url-draft.svelte.js';
	import { readToolsState, toolsParameters, type ToolsState } from './list-state';

	type Tool = 'duplicates' | 'tags' | 'citation-styles';
	type Tag = {
		id: string;
		name: string;
		accessible_item_count: number;
		authorization: AuthorizationDecisionSet;
	};
	type CitationStyle = { key: string; name: string; scope: 'builtin' | 'custom' };

	const location = $derived(readToolsState(page.url.searchParams));
	const activeTool = $derived(location.tool);
	const mode = $derived(location.mode);
	let scannedMode = $state('');
	const submittedTagFilter = $derived(location.tagSearch);
	const tagFilter = createUrlDraft({
		read: (url) => readToolsState(url.searchParams).tagSearch,
		href: (tagSearch) => toolsHref({ tagSearch, tagPage: 1 })
	});
	const tagPage = $derived(location.tagPage);
	let sourceTag = $state('');
	let targetTag = $state('');
	const styleQuery = $derived(location.styleQuery);
	const styleSearch = createUrlDraft({
		read: (url) => readToolsState(url.searchParams).styleQuery,
		href: (styleQuery) => toolsHref({ styleQuery })
	});
	let styleName = $state('');
	let styleCsl = $state('');
	let busy = $state(false);
	let error = $state('');
	let notice = $state('');
	let pendingTag = $state<Tag | null>(null);
	let confirmDeleteOpen = $state(false);
	let renameTarget = $state<Tag | null>(null);
	let renameOpen = $state(false);
	let pendingStyle = $state<CitationStyle | null>(null);
	let confirmStyleDeleteOpen = $state(false);
	const pageSize = $derived(location.pageSize);
	const queryClient = useQueryClient();
	const workspace = getWorkspaceContext();
	const { workspaceId } = workspace;
	function toolsHref(change: Partial<ToolsState>) {
		const parameters = toolsParameters({ ...location, ...change });
		const path = workspaceHref(workspaceId, 'tools');
		return resolve(parameters ? `${path}?${parameters}` : path);
	}
	function navigateTools(change: Partial<ToolsState>, history: 'push' | 'replace' = 'push') {
		void goto(toolsHref(change), {
			reset: false,
			replace: history === 'replace'
		});
	}

	const tags = createQuery(() => ({
		...tagsQuery(workspaceId, submittedTagFilter, (tagPage - 1) * pageSize, pageSize),
		enabled: activeTool === 'tags'
	}));
	const duplicates = createQuery(() => ({
		...duplicateScanQuery(workspaceId, scannedMode),
		// A stale result must never turn navigation or invalidation into a new scan.
		enabled: false
	}));
	const citationStyles = createQuery(() => ({
		...citationStylesQuery(workspaceId, styleQuery),
		enabled: activeTool === 'citation-styles'
	}));

	const tagPageCount = $derived(Math.max(1, Math.ceil((tags.data?.total ?? 0) / pageSize)));
	$effect(() => {
		// Only a completed server response can establish that the current page disappeared.
		if (activeTool === 'tags' && tags.isSuccess && !tags.isFetching && tagPage > tagPageCount)
			navigateTools({ tagPage: tagPageCount }, 'replace');
	});

	async function tagMutation(operation: () => Promise<unknown>, success: string): Promise<boolean> {
		if (busy) return false;
		busy = true;
		error = '';
		notice = '';
		try {
			await operation();
			// Rename, delete and merge also change each Item's Tag projections.
			await Promise.all([
				invalidateTags(queryClient, workspaceId),
				invalidateLibrary(queryClient, workspaceId)
			]);
			notice = success;
			return true;
		} catch (reason) {
			error = apiErrorMessage(reason, $t('Tag action failed'));
			if (reason instanceof ApiError && reason.code === 'tag_conflict') {
				await Promise.all([
					invalidateTags(queryClient, workspaceId),
					invalidateLibrary(queryClient, workspaceId)
				]);
			}
			return false;
		} finally {
			busy = false;
		}
	}

	function renameTag(tag: Tag) {
		error = '';
		renameTarget = tag;
		renameOpen = true;
	}

	async function confirmRenameTag(name: string) {
		const tag = renameTarget;
		if (!tag || !name.trim() || busy) return;
		if (name === tag.name) {
			renameOpen = false;
			renameTarget = null;
			return;
		}
		const saved = await tagMutation(
			() =>
				workspace.api.request('PATCH', '/workspaces/{workspace_id}/tags/{tag_id}', {
					params: { path: { tag_id: tag.id } },
					body: { name }
				}),
			$t('Tag renamed')
		);
		if (saved) {
			renameOpen = false;
			renameTarget = null;
		}
	}

	function deleteTag(tag: Tag) {
		error = '';
		pendingTag = tag;
		confirmDeleteOpen = true;
	}

	async function confirmDeleteTag() {
		const tag = pendingTag;
		if (!tag || busy) return;
		const saved = await tagMutation(
			() =>
				workspace.api.request('DELETE', '/workspaces/{workspace_id}/tags/{tag_id}', {
					params: { path: { tag_id: tag.id } }
				}),
			$t('Tag deleted')
		);
		if (saved) {
			confirmDeleteOpen = false;
			pendingTag = null;
		}
	}

	function mergeTags() {
		if (!sourceTag || !targetTag || sourceTag === targetTag) return;
		void tagMutation(
			() =>
				workspace.api.request('POST', '/workspaces/{workspace_id}/tags/merge', {
					body: { source_tag_id: sourceTag, target_tag_id: targetTag }
				}),
			$t('Tags merged')
		).then((saved) => {
			if (saved) {
				sourceTag = '';
				targetTag = '';
			}
		});
	}

	async function scanDuplicates() {
		if (duplicates.isFetching) return;
		error = '';
		notice = '';
		scannedMode = mode;
		await tick();
		await duplicates.refetch();
	}

	async function createStyle() {
		if (busy) return;
		const input = { name: styleName, csl: styleCsl };
		busy = true;
		error = '';
		notice = '';
		try {
			await workspace.api.request('POST', '/workspaces/{workspace_id}/citation-styles', {
				body: input
			});
			if (styleName === input.name && styleCsl === input.csl) {
				styleName = '';
				styleCsl = '';
			}
			await invalidateCitationStyles(queryClient, workspaceId);
			notice = $t('Citation Style added');
		} catch (reason) {
			error = apiErrorMessage(reason, $t('Unable to add Citation Style'));
		} finally {
			busy = false;
		}
	}

	async function deleteStyle(style: CitationStyle) {
		error = '';
		pendingStyle = style;
		confirmStyleDeleteOpen = true;
	}

	async function confirmDeleteStyle() {
		const style = pendingStyle;
		if (!style || busy) return;
		busy = true;
		error = '';
		try {
			await workspace.api.request(
				'DELETE',
				'/workspaces/{workspace_id}/citation-styles/{style_id}',
				{
					params: { path: { style_id: style.key } }
				}
			);
			await invalidateCitationStyles(queryClient, workspaceId);
			confirmStyleDeleteOpen = false;
			pendingStyle = null;
			notice = $t('Citation Style deleted');
		} catch (reason) {
			error = apiErrorMessage(reason, $t('Unable to delete Citation Style'));
		} finally {
			busy = false;
		}
	}
</script>

<SectionHeader>
	<div>
		<p class="mb-1 text-sm font-medium text-primary-700-300">{$t('Library maintenance')}</p>
		<h1>{$t('Tools')}</h1>
		<p class="text-surface-600-400">
			{$t('Review duplicates, maintain Tags, and install Citation Styles.')}
		</p>
	</div>
</SectionHeader>

<Tabs
	value={activeTool}
	onValueChange={(details) => navigateTools({ tool: (details.value ?? 'duplicates') as Tool })}
>
	<Tabs.List class="max-w-full overflow-x-auto" aria-label={$t('Library tools')}>
		<Tabs.Indicator class="bg-primary-700-300" />
		<Tabs.Trigger value="duplicates" class="whitespace-nowrap data-selected:text-primary-800-200"
			>{$t('Duplicate review')}</Tabs.Trigger
		>
		<Tabs.Trigger value="tags" class="whitespace-nowrap data-selected:text-primary-800-200"
			>{$t('Manage Tags')}</Tabs.Trigger
		>
		<Tabs.Trigger
			value="citation-styles"
			class="whitespace-nowrap data-selected:text-primary-800-200"
			>{$t('Citation Styles')}</Tabs.Trigger
		>
	</Tabs.List>

	{#if error && !renameOpen && !confirmDeleteOpen && !confirmStyleDeleteOpen}<Notice variant="error"
			>{error}</Notice
		>{/if}
	{#if notice}<Notice variant="success">{notice}</Notice>{/if}

	<Tabs.Content value="duplicates">
		<Panel padding="none">
			<div
				class="flex flex-wrap items-end justify-between gap-4 border-b border-surface-300-700 p-5"
			>
				<div>
					<h2>{$t('Duplicate review')}</h2>
					<p class="mb-0 max-w-2xl text-surface-600-400">
						{$t('Compare likely duplicate Items before deciding what to retain.')}
					</p>
				</div>
				<Button
					variant="filled"
					disabled={duplicates.isFetching}
					onclick={() => void scanDuplicates()}
					>{duplicates.isFetching ? $t('Scanning…') : $t('Check for duplicates')}</Button
				>
			</div>
			<div class="border-b border-surface-300-700 bg-surface-100-900 px-5 py-3">
				<SegmentedControl
					value={mode}
					onValueChange={(details) =>
						navigateTools({
							mode:
								details.value === 'title' || details.value === 'similar'
									? details.value
									: 'identifier'
						})}
				>
					<SegmentedControl.Label>{$t('Match criteria')}</SegmentedControl.Label>
					<SegmentedControl.Control class="flex-wrap">
						<SegmentedControl.Indicator />
						{#each [{ value: 'identifier', label: $t('Shared identifier') }, { value: 'title', label: $t('Same title') }, { value: 'similar', label: $t('Similar title') }] as option (option.value)}
							<SegmentedControl.Item value={option.value}>
								<SegmentedControl.ItemText>{option.label}</SegmentedControl.ItemText>
								<SegmentedControl.ItemHiddenInput />
							</SegmentedControl.Item>
						{/each}
					</SegmentedControl.Control>
				</SegmentedControl>
			</div>
			<div class="p-5">
				{#if !scannedMode || (duplicates.isPending && !duplicates.isFetching)}
					<div class="grid min-h-40 grid-cols-1 place-items-center text-center">
						<div class="max-w-md">
							<h3>{$t('Run a check when you are ready')}</h3>
							<p class="mb-0 text-surface-600-400">
								{$t('Quirebase will not inspect your Library until you start the check.')}
							</p>
						</div>
					</div>
				{:else if scannedMode !== mode}
					<Notice variant="success">
						{$t('The match criteria changed. Start a new check to refresh these results.')}
					</Notice>
				{:else if duplicates.isFetching}
					<LoadingState label={$t('Scanning…')} />
				{:else if duplicates.isError}
					<QueryError
						message={apiErrorMessage(duplicates.error, $t('Unable to check for duplicates.'))}
						busy={duplicates.isFetching}
						onRetry={() => void scanDuplicates()}
					/>
				{:else}{#each duplicates.data?.groups ?? [] as group, index (group
						.map((item) => item.id)
						.join(':'))}
						<article class="mb-4 rounded-lg border border-surface-300-700 p-3 last:mb-0">
							<h3>{$t('Duplicate group {number}', { number: index + 1 })}</h3>
							{#each group as item (item.id)}
								<ItemRow as="a" href={resolve(workspaceHref(workspaceId, `item/${item.id}`))}>
									<strong><RichText html={item.title_html} /></strong>
									<span class="text-surface-600-400"
										>{item.authors.map((author) => author.full_name).join('; ') ||
											$t('Unknown contributors')}</span
									>
									{#if item.doi}<code class="text-xs">{item.doi}</code>{/if}
								</ItemRow>
							{/each}
						</article>
					{:else}<p class="text-surface-600-400">{$t('No duplicate groups found.')}</p>{/each}{/if}
			</div>
		</Panel>
	</Tabs.Content>
	<Tabs.Content value="tags">
		<div class="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(18rem,1fr)]">
			<Panel>
				<SectionHeader class="flex-col items-stretch sm:flex-row sm:items-center">
					<div>
						<h2>{$t('Manage Tags')}</h2>
						<p class="text-surface-600-400">
							{$t('{count, plural, one {# Tag} other {# Tags}}', {
								count: tags.data?.total ?? 0
							})}
						</p>
					</div>
					{#snippet actions()}
						<input
							class="input w-full sm:w-auto sm:min-w-36"
							bind:value={tagFilter.value}
							placeholder={$t('Filter Tags')}
						/>
					{/snippet}
				</SectionHeader>
				{#if tags.isError}<QueryError
						message={apiErrorMessage(tags.error, $t('Unable to load Tags'))}
						busy={tags.isFetching}
						onRetry={() => void tags.refetch()}
					/>
				{:else if tags.isPending}<LoadingState label={$t('Loading Tags…')} />
				{:else}{#each tags.data?.items ?? [] as tag (tag.id)}
						<ItemRow
							class="grid-cols-1 items-start gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center"
						>
							<div>
								<strong>{tag.name}</strong>
								<p class="mb-0 text-sm text-surface-600-400">
									{$t('{count, plural, one {# Item} other {# Items}}', {
										count: tag.accessible_item_count
									})}
								</p>
							</div>
							<div class="flex flex-wrap gap-2">
								<Button
									as="a"
									href={resolve(
										workspaceHref(workspaceId, `library?tag=${encodeURIComponent(tag.id)}`)
									)}>{$t('View Items')}</Button
								>
								{#if can(tag.authorization, 'tag.manage')}<Button
										disabled={busy}
										onclick={() => renameTag(tag)}>{$t('Rename')}</Button
									><Button variant="danger" disabled={busy} onclick={() => deleteTag(tag)}
										>{$t('Delete')}</Button
									>{/if}
							</div>
						</ItemRow>
					{:else}<p class="text-surface-600-400">{$t('No Tags match this filter.')}</p>{/each}{/if}
				<Pagination
					page={tagPage}
					pageCount={tagPageCount}
					{pageSize}
					total={tags.data?.total ?? 0}
					onPageSize={(size) => {
						navigateTools({ pageSize: size, tagPage: 1 });
					}}
					busy={tags.isFetching}
					label={$t('Tag pages')}
					onPage={(next) => navigateTools({ tagPage: next })}
				/>
			</Panel>
			<Panel as="aside" class="grid grid-cols-1 gap-3 self-start">
				<h2>{$t('Merge Tags')}</h2>
				<p class="text-sm text-surface-600-400">
					{$t('Move every assignment from the source Tag into the target Tag.')}
				</p>
				<TagSelect
					label={$t('Source Tag')}
					bind:value={sourceTag}
					emptyLabel={$t('Select a Tag')}
					disabled={busy}
					manageOnly
				/>
				<TagSelect
					label={$t('Target Tag')}
					bind:value={targetTag}
					emptyLabel={$t('Select a Tag')}
					disabled={busy}
				/>
				<Button
					variant="filled"
					disabled={busy || !sourceTag || !targetTag || sourceTag === targetTag}
					onclick={mergeTags}>{$t('Merge Tags')}</Button
				>
			</Panel>
		</div>
	</Tabs.Content>
	<Tabs.Content value="citation-styles">
		<div class="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(20rem,1fr)]">
			<Panel>
				<SectionHeader class="flex-col items-stretch sm:flex-row sm:items-center">
					<div>
						<h2>{$t('Citation Style catalog')}</h2>
						<p class="text-surface-600-400">
							{$t('Built-in CSL styles and styles installed by you.')}
						</p>
					</div>
					{#snippet actions()}
						<input
							class="input w-full sm:w-auto sm:min-w-36"
							bind:value={styleSearch.value}
							placeholder={$t('Search styles')}
						/>
					{/snippet}
				</SectionHeader>
				{#if citationStyles.isError}<QueryError
						message={apiErrorMessage(citationStyles.error, $t('Unable to load Citation Styles.'))}
						busy={citationStyles.isFetching}
						onRetry={() => void citationStyles.refetch()}
					/>{/if}
				{#if citationStyles.isPending}<LoadingState label={$t('Loading Citation Styles…')} />{/if}
				{#each citationStyles.data?.styles ?? [] as style (style.key)}
					<ItemRow
						class="grid-cols-1 items-start gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center"
					>
						<div>
							<strong>{style.name}</strong>
							<p class="mb-0 text-sm text-surface-600-400">{style.scope}</p>
						</div>
						{#if style.scope === 'custom' && workspace.can('citation_style.manage')}<Button
								variant="danger"
								disabled={busy}
								onclick={() => deleteStyle(style)}>{$t('Delete')}</Button
							>{/if}
					</ItemRow>
				{:else}{#if citationStyles.isSuccess}<p class="text-surface-600-400">
							{$t('No Citation Styles match this search.')}
						</p>{/if}{/each}
			</Panel>
			{#if workspace.can('citation_style.manage')}<Panel
					as="form"
					class="grid grid-cols-1 gap-3 self-start"
					onsubmit={(event) => {
						event.preventDefault();
						void createStyle();
					}}
				>
					<h2>{$t('Add custom Citation Style')}</h2>
					<label>{$t('Style name')}<input class="input" bind:value={styleName} required /></label>
					<label
						>{$t('CSL XML')}<textarea
							class="textarea min-h-64 font-mono text-xs"
							bind:value={styleCsl}
							required></textarea></label
					>
					<Button variant="filled" disabled={busy}>{$t('Install Citation Style')}</Button>
				</Panel>{/if}
		</div>
	</Tabs.Content>
</Tabs>

<ConfirmDialog
	bind:open={confirmDeleteOpen}
	title={$t('Delete this Tag from all accessible Items?')}
	body={pendingTag?.name ?? ''}
	confirmLabel={$t('Delete Tag')}
	{busy}
	error={confirmDeleteOpen ? error : ''}
	onConfirm={() => void confirmDeleteTag()}
/>
<PromptDialog
	bind:open={renameOpen}
	title={$t('Rename Tag')}
	body={$t('Choose a new name for this Tag.')}
	label={$t('New Tag name')}
	placeholder={renameTarget?.name ?? ''}
	initialValue={renameTarget?.name ?? ''}
	confirmLabel={$t('Rename')}
	{busy}
	error={renameOpen ? error : ''}
	onConfirm={(name) => void confirmRenameTag(name)}
/>
<ConfirmDialog
	bind:open={confirmStyleDeleteOpen}
	title={$t('Delete this Citation Style?')}
	body={pendingStyle?.name ?? ''}
	confirmLabel={$t('Delete Style')}
	{busy}
	error={confirmStyleDeleteOpen ? error : ''}
	onConfirm={() => void confirmDeleteStyle()}
/>
