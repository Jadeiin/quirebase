<script lang="ts">
	import { resolve } from '$app/paths';
	import { createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { apiRequest, type ItemSummary } from '$lib/api/client';
	import RichText from '$lib/design/RichText.svelte';
	import { t } from '$lib/i18n';

	type Tool = 'duplicates' | 'tags' | 'citation-styles';
	type Tag = { id: string; name: string; accessible_item_count: number };
	type CitationStyle = { key: string; name: string; scope: 'builtin' | 'custom' };

	let activeTool = $state<Tool>('duplicates');
	let mode = $state('doi');
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
		queryFn: () => apiRequest<Tag[]>('/tags')
	}));
	const duplicates = createQuery(() => ({
		queryKey: ['duplicates', mode],
		queryFn: () => apiRequest<{ groups: ItemSummary[][] }>(`/duplicates?mode=${mode}`)
	}));
	const citationStyles = createQuery(() => ({
		queryKey: ['citation-styles', styleQuery],
		queryFn: () =>
			apiRequest<{ styles: CitationStyle[] }>(
				`/citation-styles?query=${encodeURIComponent(styleQuery)}&limit=50`
			)
	}));

	const filteredTags = $derived(
		(tags.data ?? []).filter((tag) =>
			tag.name.toLocaleLowerCase().includes(tagFilter.toLocaleLowerCase())
		)
	);
	const tagPageCount = $derived(Math.max(1, Math.ceil(filteredTags.length / pageSize)));
	const visibleTags = $derived(filteredTags.slice((tagPage - 1) * pageSize, tagPage * pageSize));

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
			error = reason instanceof Error ? reason.message : $t('Tag action failed');
			return false;
		} finally {
			busy = false;
		}
	}

	function renameTag(tag: Tag) {
		const name = window.prompt($t('New Tag name'), tag.name);
		if (name && name !== tag.name) {
			void tagMutation(
				() => apiRequest(`/tags/${tag.id}`, { method: 'PATCH', body: { name } }),
				$t('Tag renamed')
			);
		}
	}

	function deleteTag(tag: Tag) {
		if (window.confirm($t('Delete this Tag from all accessible Items?'))) {
			void tagMutation(
				() => apiRequest(`/tags/${tag.id}`, { method: 'DELETE' }),
				$t('Tag deleted')
			);
		}
	}

	function mergeTags() {
		if (!sourceTag || !targetTag || sourceTag === targetTag) return;
		void tagMutation(
			() =>
				apiRequest('/tags/merge', {
					method: 'POST',
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

	async function createStyle() {
		busy = true;
		error = '';
		notice = '';
		try {
			await apiRequest('/citation-styles', {
				method: 'POST',
				body: { name: styleName, csl: styleCsl }
			});
			styleName = '';
			styleCsl = '';
			await queryClient.invalidateQueries({ queryKey: ['citation-styles'] });
			notice = $t('Citation Style added');
		} catch (reason) {
			error = reason instanceof Error ? reason.message : $t('Unable to add Citation Style');
		} finally {
			busy = false;
		}
	}

	async function deleteStyle(style: CitationStyle) {
		busy = true;
		error = '';
		try {
			await apiRequest(`/citation-styles/${style.key}`, { method: 'DELETE' });
			await queryClient.invalidateQueries({ queryKey: ['citation-styles'] });
			notice = $t('Citation Style deleted');
		} catch (reason) {
			error = reason instanceof Error ? reason.message : $t('Unable to delete Citation Style');
		} finally {
			busy = false;
		}
	}
</script>

<div class="workspace-header">
	<div>
		<p class="eyebrow">{$t('Library maintenance')}</p>
		<h1>{$t('Tools')}</h1>
		<p class="muted">{$t('Review duplicates, maintain Tags, and install Citation Styles.')}</p>
	</div>
</div>

<div class="tabs" role="tablist" aria-label={$t('Library tools')}>
	<button
		id="tool-tab-duplicates"
		role="tab"
		aria-selected={activeTool === 'duplicates'}
		aria-controls="tool-panel-duplicates"
		tabindex={activeTool === 'duplicates' ? 0 : -1}
		class={['button', activeTool === 'duplicates' && 'button-primary']}
		onkeydown={(event) => handleTabKey(event, 'duplicates')}
		onclick={() => (activeTool = 'duplicates')}>{$t('Duplicate review')}</button
	>
	<button
		id="tool-tab-tags"
		role="tab"
		aria-selected={activeTool === 'tags'}
		aria-controls="tool-panel-tags"
		tabindex={activeTool === 'tags' ? 0 : -1}
		class={['button', activeTool === 'tags' && 'button-primary']}
		onkeydown={(event) => handleTabKey(event, 'tags')}
		onclick={() => (activeTool = 'tags')}>{$t('Manage Tags')}</button
	>
	<button
		id="tool-tab-citation-styles"
		role="tab"
		aria-selected={activeTool === 'citation-styles'}
		aria-controls="tool-panel-citation-styles"
		tabindex={activeTool === 'citation-styles' ? 0 : -1}
		class={['button', activeTool === 'citation-styles' && 'button-primary']}
		onkeydown={(event) => handleTabKey(event, 'citation-styles')}
		onclick={() => (activeTool = 'citation-styles')}>{$t('Citation Styles')}</button
	>
</div>

{#if error}<p class="error" role="alert">{error}</p>{/if}
{#if notice}<p class="notice" role="status">{notice}</p>{/if}

{#if activeTool === 'duplicates'}
	<div id="tool-panel-duplicates" role="tabpanel" aria-labelledby="tool-tab-duplicates">
		<section class="panel">
			<div class="workspace-header">
				<div>
					<h2>{$t('Duplicate review')}</h2>
					<p class="muted">
						{$t('Compare likely duplicate Items before deciding what to retain.')}
					</p>
				</div>
				<select class="field compact" bind:value={mode}>
					<option value="doi">{$t('Same DOI')}</option><option value="title"
						>{$t('Same title')}</option
					><option value="similar">{$t('Similar title')}</option>
				</select>
			</div>
			{#if duplicates.isPending}<p class="muted">{$t('Scanning…')}</p>
			{:else}{#each duplicates.data?.groups ?? [] as group, index (group
					.map((item) => item.id)
					.join(':'))}
					<article class="mb-4 rounded-lg border border-line p-3 last:mb-0">
						<h3>{$t('Duplicate group')} {index + 1}</h3>
						{#each group as item (item.id)}
							<a class="item-row" href={resolve('/(app)/item/[itemId]', { itemId: item.id })}>
								<strong><RichText html={item.title_html} /></strong>
								<span class="muted">{item.authors ?? $t('Unknown contributors')}</span>
								{#if item.doi}<code class="text-xs">{item.doi}</code>{/if}
							</a>
						{/each}
					</article>
				{:else}<p class="muted">{$t('No duplicate groups found.')}</p>{/each}{/if}
		</section>
	</div>
{:else if activeTool === 'tags'}
	<div
		class="grid gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(18rem,1fr)]"
		id="tool-panel-tags"
		role="tabpanel"
		aria-labelledby="tool-tab-tags"
	>
		<section class="panel">
			<div class="workspace-header">
				<div>
					<h2>{$t('Manage Tags')}</h2>
					<p class="muted">{filteredTags.length} {$t('Tags')}</p>
				</div>
				<input
					class="field compact"
					bind:value={tagFilter}
					oninput={() => (tagPage = 1)}
					placeholder={$t('Filter Tags')}
				/>
			</div>
			{#each visibleTags as tag (tag.id)}
				<div class="item-row grid-cols-[minmax(0,1fr)_auto] items-center">
					<div>
						<strong>{tag.name}</strong>
						<p class="muted mb-0 text-sm">{tag.accessible_item_count} {$t('Items')}</p>
					</div>
					<div class="toolbar">
						<a class="button" href={resolve(`/library?tag=${encodeURIComponent(tag.id)}`)}
							>{$t('View Items')}</a
						>
						<button class="button" disabled={busy} onclick={() => renameTag(tag)}
							>{$t('Rename')}</button
						>
						<button class="button text-danger" disabled={busy} onclick={() => deleteTag(tag)}
							>{$t('Delete')}</button
						>
					</div>
				</div>
			{:else}<p class="muted">{$t('No Tags match this filter.')}</p>{/each}
			{#if tagPageCount > 1}
				<nav class="pagination" aria-label={$t('Tag pages')}>
					<button class="button" disabled={tagPage === 1} onclick={() => (tagPage -= 1)}
						>{$t('Previous')}</button
					>
					<span>{$t('Page')} {tagPage} / {tagPageCount}</span>
					<button class="button" disabled={tagPage === tagPageCount} onclick={() => (tagPage += 1)}
						>{$t('Next')}</button
					>
				</nav>
			{/if}
		</section>
		<aside class="panel stack self-start">
			<h2>{$t('Merge Tags')}</h2>
			<p class="muted text-sm">
				{$t('Move every assignment from the source Tag into the target Tag.')}
			</p>
			<label
				>{$t('Source Tag')}<select class="field" bind:value={sourceTag}
					><option value="">{$t('Select a Tag')}</option
					>{#each tags.data ?? [] as tag (tag.id)}<option value={tag.id}>{tag.name}</option
						>{/each}</select
				></label
			>
			<label
				>{$t('Target Tag')}<select class="field" bind:value={targetTag}
					><option value="">{$t('Select a Tag')}</option
					>{#each tags.data ?? [] as tag (tag.id)}<option value={tag.id}>{tag.name}</option
						>{/each}</select
				></label
			>
			<button
				class="button button-primary"
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
		<section class="panel">
			<div class="workspace-header">
				<div>
					<h2>{$t('Citation Style catalog')}</h2>
					<p class="muted">{$t('Built-in CSL styles and styles installed by you.')}</p>
				</div>
				<input class="field compact" bind:value={styleQuery} placeholder={$t('Search styles')} />
			</div>
			{#each citationStyles.data?.styles ?? [] as style (style.key)}
				<div class="item-row grid-cols-[minmax(0,1fr)_auto] items-center">
					<div>
						<strong>{style.name}</strong>
						<p class="muted mb-0 text-sm">{style.scope}</p>
					</div>
					{#if style.scope === 'custom'}<button
							class="button text-danger"
							disabled={busy}
							onclick={() => deleteStyle(style)}>{$t('Delete')}</button
						>{/if}
				</div>
			{:else}<p class="muted">{$t('No Citation Styles match this search.')}</p>{/each}
		</section>
		<form
			class="panel stack self-start"
			onsubmit={(event) => {
				event.preventDefault();
				void createStyle();
			}}
		>
			<h2>{$t('Add custom Citation Style')}</h2>
			<label>{$t('Style name')}<input class="field" bind:value={styleName} required /></label>
			<label
				>{$t('CSL XML')}<textarea
					class="field min-h-64 font-mono text-xs"
					bind:value={styleCsl}
					required></textarea></label
			>
			<button class="button button-primary" disabled={busy}>{$t('Install Citation Style')}</button>
		</form>
	</div>
{/if}
