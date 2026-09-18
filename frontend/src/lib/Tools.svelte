<script lang="ts">
	import { resolve } from '$app/paths';
	import { createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { apiRequest } from '$lib/api/client';
	import { apiErrorMessage } from '$lib/api/errors';
	import RichText from '$lib/design/RichText.svelte';
	import { t } from '$lib/i18n';

	type Tool = 'duplicates' | 'tags' | 'citation-styles';
	type Tag = { id: string; name: string; accessible_item_count: number };
	type CitationStyle = { key: string; name: string; scope: 'builtin' | 'custom' };

	let activeTool = $state<Tool>('duplicates');
	let mode = $state('doi');
	let scannedMode = $state('');
	let tagFilter = $state('');
	let tagPage = $state(1);
	let sourceTag = $state('');
	let targetTag = $state('');
	let styleQuery = $state('');
	let styleName = $state('');
	let styleCsl = $state('');
	let busy = $state(false);
	let error = $state('');
	let notice = $state('');
	const pageSize = 20;
	const toolOrder: Tool[] = ['duplicates', 'tags', 'citation-styles'];
	const queryClient = useQueryClient();

	const tags = createQuery(() => ({
		queryKey: ['tags'],
		queryFn: () => apiRequest('GET', '/tags')
	}));
	const duplicates = createQuery(() => ({
		queryKey: ['duplicates', scannedMode],
		queryFn: () => apiRequest('GET', '/duplicates', { params: { query: { mode: scannedMode } } }),
		enabled: Boolean(scannedMode)
	}));
	const citationStyles = createQuery(() => ({
		queryKey: ['citation-styles', styleQuery],
		queryFn: () =>
			apiRequest('GET', '/citation-styles', {
				params: { query: { query: styleQuery, limit: 50 } }
			})
	}));

	const filteredTags = $derived(
		(tags.data ?? []).filter((tag) =>
			tag.name.toLocaleLowerCase().includes(tagFilter.toLocaleLowerCase())
		)
	);
	const tagPageCount = $derived(Math.max(1, Math.ceil(filteredTags.length / pageSize)));
	const currentTagPage = $derived(Math.min(tagPage, tagPageCount));
	const visibleTags = $derived(
		filteredTags.slice((currentTagPage - 1) * pageSize, currentTagPage * pageSize)
	);

	async function tagMutation(operation: () => Promise<unknown>, success: string): Promise<boolean> {
		busy = true;
		error = '';
		notice = '';
		try {
			await operation();
			await queryClient.invalidateQueries({ queryKey: ['tags'] });
			notice = success;
			return true;
		} catch (reason) {
			error = apiErrorMessage(reason, $t('Tag action failed'));
			return false;
		} finally {
			busy = false;
		}
	}

	function renameTag(tag: Tag) {
		const name = window.prompt($t('New Tag name'), tag.name);
		if (name && name !== tag.name) {
			void tagMutation(
				() =>
					apiRequest('PATCH', '/tags/{tag_id}', {
						params: { path: { tag_id: tag.id } },
						body: { name }
					}),
				$t('Tag renamed')
			);
		}
	}

	function deleteTag(tag: Tag) {
		if (window.confirm($t('Delete this Tag from all accessible Items?'))) {
			void tagMutation(
				() =>
					apiRequest('DELETE', '/tags/{tag_id}', {
						params: { path: { tag_id: tag.id } }
					}),
				$t('Tag deleted')
			);
		}
	}

	function mergeTags() {
		if (!sourceTag || !targetTag || sourceTag === targetTag) return;
		void tagMutation(
			() =>
				apiRequest('POST', '/tags/merge', {
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

	function handleTabKey(event: KeyboardEvent, tool: Tool) {
		const direction = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0;
		if (!direction) return;
		event.preventDefault();
		const index = toolOrder.indexOf(tool);
		activeTool = toolOrder[(index + direction + toolOrder.length) % toolOrder.length];
		queueMicrotask(() => document.getElementById(`tool-tab-${activeTool}`)?.focus());
	}

	async function scanDuplicates() {
		error = '';
		notice = '';
		if (scannedMode === mode) await duplicates.refetch();
		else scannedMode = mode;
	}

	async function createStyle() {
		busy = true;
		error = '';
		notice = '';
		try {
			await apiRequest('POST', '/citation-styles', {
				body: { name: styleName, csl: styleCsl }
			});
			styleName = '';
			styleCsl = '';
			await queryClient.invalidateQueries({ queryKey: ['citation-styles'] });
			notice = $t('Citation Style added');
		} catch (reason) {
			error = apiErrorMessage(reason, $t('Unable to add Citation Style'));
		} finally {
			busy = false;
		}
	}

	async function deleteStyle(style: CitationStyle) {
		busy = true;
		error = '';
		try {
			await apiRequest('DELETE', '/citation-styles/{style_id}', {
				params: { path: { style_id: style.key } }
			});
			await queryClient.invalidateQueries({ queryKey: ['citation-styles'] });
			notice = $t('Citation Style deleted');
		} catch (reason) {
			error = apiErrorMessage(reason, $t('Unable to delete Citation Style'));
		} finally {
			busy = false;
		}
	}
</script>

<div class="workspace-header">
	<div>
		<p class="eyebrow">{$t('Library maintenance')}</p>
		<h1>{$t('Tools')}</h1>
		<p class="text-surface-600-400">
			{$t('Review duplicates, maintain Tags, and install Citation Styles.')}
		</p>
	</div>
</div>

<div
	class="mb-5 inline-flex max-w-full gap-1 overflow-x-auto rounded-lg border border-surface-300-700 bg-surface-200-800 p-1"
	role="tablist"
	aria-label={$t('Library tools')}
>
	<button
		id="tool-tab-duplicates"
		role="tab"
		aria-selected={activeTool === 'duplicates'}
		aria-controls="tool-panel-duplicates"
		tabindex={activeTool === 'duplicates' ? 0 : -1}
		class={[
			'rounded-md border-0 px-3.5 py-2 text-sm font-semibold whitespace-nowrap transition-colors',
			activeTool === 'duplicates'
				? 'bg-surface-50-950 text-primary-800-200 shadow-sm'
				: 'bg-transparent text-surface-600-400 hover:text-surface-900-100'
		]}
		onkeydown={(event) => handleTabKey(event, 'duplicates')}
		onclick={() => (activeTool = 'duplicates')}>{$t('Duplicate review')}</button
	>
	<button
		id="tool-tab-tags"
		role="tab"
		aria-selected={activeTool === 'tags'}
		aria-controls="tool-panel-tags"
		tabindex={activeTool === 'tags' ? 0 : -1}
		class={[
			'rounded-md border-0 px-3.5 py-2 text-sm font-semibold whitespace-nowrap transition-colors',
			activeTool === 'tags'
				? 'bg-surface-50-950 text-primary-800-200 shadow-sm'
				: 'bg-transparent text-surface-600-400 hover:text-surface-900-100'
		]}
		onkeydown={(event) => handleTabKey(event, 'tags')}
		onclick={() => (activeTool = 'tags')}>{$t('Manage Tags')}</button
	>
	<button
		id="tool-tab-citation-styles"
		role="tab"
		aria-selected={activeTool === 'citation-styles'}
		aria-controls="tool-panel-citation-styles"
		tabindex={activeTool === 'citation-styles' ? 0 : -1}
		class={[
			'rounded-md border-0 px-3.5 py-2 text-sm font-semibold whitespace-nowrap transition-colors',
			activeTool === 'citation-styles'
				? 'bg-surface-50-950 text-primary-800-200 shadow-sm'
				: 'bg-transparent text-surface-600-400 hover:text-surface-900-100'
		]}
		onkeydown={(event) => handleTabKey(event, 'citation-styles')}
		onclick={() => (activeTool = 'citation-styles')}>{$t('Citation Styles')}</button
	>
</div>

{#if error}<p class="text-error-700-300" role="alert">{error}</p>{/if}
{#if notice}<p
		class="rounded-base border border-success-200-800 preset-tonal-success px-4 py-3 text-success-900-100"
		role="status"
	>
		{notice}
	</p>{/if}

{#if activeTool === 'duplicates'}
	<div id="tool-panel-duplicates" role="tabpanel" aria-labelledby="tool-tab-duplicates">
		<section
			class="overflow-hidden card border border-surface-300-700 bg-surface-50-950 p-0 shadow-sm"
		>
			<div
				class="flex flex-wrap items-end justify-between gap-4 border-b border-surface-300-700 p-5"
			>
				<div>
					<h2>{$t('Duplicate review')}</h2>
					<p class="mb-0 max-w-2xl text-surface-600-400">
						{$t('Compare likely duplicate Items before deciding what to retain.')}
					</p>
				</div>
				<button
					class="btn preset-filled-primary-700-300 font-semibold"
					disabled={duplicates.isFetching}
					onclick={() => void scanDuplicates()}
					>{duplicates.isFetching ? $t('Scanning…') : $t('Check for duplicates')}</button
				>
			</div>
			<div class="bg-surface/60 border-b border-surface-300-700 px-5 py-3">
				<p class="mb-2 text-xs font-bold tracking-wide text-surface-600-400 uppercase">
					{$t('Match criteria')}
				</p>
				<div class="flex flex-wrap gap-2" role="group" aria-label={$t('Match criteria')}>
					{#each [{ value: 'doi', label: $t('Same DOI') }, { value: 'title', label: $t('Same title') }, { value: 'similar', label: $t('Similar title') }] as option (option.value)}
						<button
							type="button"
							class={[
								'rounded-full border px-3 py-1.5 text-sm font-medium',
								mode === option.value
									? 'border-primary-700-300 bg-primary-50-950 text-primary-800-200'
									: 'border-surface-300-700 bg-surface-50-950 text-surface-600-400 hover:border-surface-400-600'
							]}
							aria-pressed={mode === option.value}
							onclick={() => (mode = option.value)}>{option.label}</button
						>
					{/each}
				</div>
			</div>
			<div class="p-5">
				{#if !scannedMode}
					<div class="grid min-h-40 place-items-center text-center">
						<div class="max-w-md">
							<h3>{$t('Run a check when you are ready')}</h3>
							<p class="mb-0 text-surface-600-400">
								{$t('Quirebase will not inspect your Library until you start the check.')}
							</p>
						</div>
					</div>
				{:else if scannedMode !== mode}
					<p
						class="rounded-base border border-success-200-800 preset-tonal-success px-4 py-3 text-success-900-100"
						role="status"
					>
						{$t('The match criteria changed. Start a new check to refresh these results.')}
					</p>
				{:else if duplicates.isPending || duplicates.isFetching}
					<p class="text-surface-600-400">{$t('Scanning…')}</p>
				{:else}{#each duplicates.data?.groups ?? [] as group, index (group
						.map((item) => item.id)
						.join(':'))}
						<article class="mb-4 rounded-lg border border-surface-300-700 p-3 last:mb-0">
							<h3>{$t('Duplicate group')} {index + 1}</h3>
							{#each group as item (item.id)}
								<a class="item-row" href={resolve('/(app)/item/[itemId]', { itemId: item.id })}>
									<strong><RichText html={item.title_html} /></strong>
									<span class="text-surface-600-400"
										>{item.authors ?? $t('Unknown contributors')}</span
									>
									{#if item.doi}<code class="text-xs">{item.doi}</code>{/if}
								</a>
							{/each}
						</article>
					{:else}<p class="text-surface-600-400">{$t('No duplicate groups found.')}</p>{/each}{/if}
			</div>
		</section>
	</div>
{:else if activeTool === 'tags'}
	<div
		class="grid gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(18rem,1fr)]"
		id="tool-panel-tags"
		role="tabpanel"
		aria-labelledby="tool-tab-tags"
	>
		<section class="card border border-surface-300-700 bg-surface-50-950 p-5 shadow-sm">
			<div class="workspace-header">
				<div>
					<h2>{$t('Manage Tags')}</h2>
					<p class="text-surface-600-400">{filteredTags.length} {$t('Tags')}</p>
				</div>
				<input
					class="compact input"
					bind:value={tagFilter}
					oninput={() => (tagPage = 1)}
					placeholder={$t('Filter Tags')}
				/>
			</div>
			{#each visibleTags as tag (tag.id)}
				<div class="item-row grid-cols-[minmax(0,1fr)_auto] items-center">
					<div>
						<strong>{tag.name}</strong>
						<p class="mb-0 text-sm text-surface-600-400">
							{tag.accessible_item_count}
							{$t('Items')}
						</p>
					</div>
					<div class="toolbar">
						<a
							class="btn preset-tonal-surface font-semibold"
							href={resolve(`/library?tag=${encodeURIComponent(tag.id)}`)}>{$t('View Items')}</a
						>
						<button
							class="btn preset-tonal-surface font-semibold"
							disabled={busy}
							onclick={() => renameTag(tag)}>{$t('Rename')}</button
						>
						<button
							class="btn preset-tonal-error font-semibold"
							disabled={busy}
							onclick={() => deleteTag(tag)}>{$t('Delete')}</button
						>
					</div>
				</div>
			{:else}<p class="text-surface-600-400">{$t('No Tags match this filter.')}</p>{/each}
			{#if tagPageCount > 1}
				<nav class="pagination" aria-label={$t('Tag pages')}>
					<button
						class="btn preset-tonal-surface font-semibold"
						disabled={currentTagPage === 1}
						onclick={() => (tagPage = currentTagPage - 1)}>{$t('Previous')}</button
					>
					<span>{$t('Page')} {currentTagPage} / {tagPageCount}</span>
					<button
						class="btn preset-tonal-surface font-semibold"
						disabled={currentTagPage === tagPageCount}
						onclick={() => (tagPage = currentTagPage + 1)}>{$t('Next')}</button
					>
				</nav>
			{/if}
		</section>
		<aside
			class="stack self-start card border border-surface-300-700 bg-surface-50-950 p-5 shadow-sm"
		>
			<h2>{$t('Merge Tags')}</h2>
			<p class="text-sm text-surface-600-400">
				{$t('Move every assignment from the source Tag into the target Tag.')}
			</p>
			<label
				>{$t('Source Tag')}<select class="select" bind:value={sourceTag}
					><option value="">{$t('Select a Tag')}</option
					>{#each tags.data ?? [] as tag (tag.id)}<option value={tag.id}>{tag.name}</option
						>{/each}</select
				></label
			>
			<label
				>{$t('Target Tag')}<select class="select" bind:value={targetTag}
					><option value="">{$t('Select a Tag')}</option
					>{#each tags.data ?? [] as tag (tag.id)}<option value={tag.id}>{tag.name}</option
						>{/each}</select
				></label
			>
			<button
				class="btn preset-filled-primary-700-300 font-semibold"
				disabled={busy || !sourceTag || !targetTag || sourceTag === targetTag}
				onclick={mergeTags}>{$t('Merge Tags')}</button
			>
		</aside>
	</div>
{:else}
	<div
		class="grid gap-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(20rem,1fr)]"
		id="tool-panel-citation-styles"
		role="tabpanel"
		aria-labelledby="tool-tab-citation-styles"
	>
		<section class="card border border-surface-300-700 bg-surface-50-950 p-5 shadow-sm">
			<div class="workspace-header">
				<div>
					<h2>{$t('Citation Style catalog')}</h2>
					<p class="text-surface-600-400">
						{$t('Built-in CSL styles and styles installed by you.')}
					</p>
				</div>
				<input class="compact input" bind:value={styleQuery} placeholder={$t('Search styles')} />
			</div>
			{#each citationStyles.data?.styles ?? [] as style (style.key)}
				<div class="item-row grid-cols-[minmax(0,1fr)_auto] items-center">
					<div>
						<strong>{style.name}</strong>
						<p class="mb-0 text-sm text-surface-600-400">{style.scope}</p>
					</div>
					{#if style.scope === 'custom'}<button
							class="btn preset-tonal-error font-semibold"
							disabled={busy}
							onclick={() => deleteStyle(style)}>{$t('Delete')}</button
						>{/if}
				</div>
			{:else}<p class="text-surface-600-400">
					{$t('No Citation Styles match this search.')}
				</p>{/each}
		</section>
		<form
			class="stack self-start card border border-surface-300-700 bg-surface-50-950 p-5 shadow-sm"
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
			<button class="btn preset-filled-primary-700-300 font-semibold" disabled={busy}
				>{$t('Install Citation Style')}</button
			>
		</form>
	</div>
{/if}
