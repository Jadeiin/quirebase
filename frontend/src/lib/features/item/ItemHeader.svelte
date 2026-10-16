<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import type { components } from '#lib/api/schema.js';
	import SectionTabs from '#lib/design/SectionTabs.svelte';
	import SectionTab from '#lib/design/SectionTab.svelte';
	import RichText from '#lib/design/RichText.svelte';
	import ItemActions from '#lib/features/item/ItemActions.svelte';
	import { msg, t, type MessageKey } from '#lib/i18n.js';
	import type { ItemOverview, ItemSection } from './queries';
	import { getWorkspaceContext } from '#lib/workspaces/context.svelte.js';
	import { workspaceHref } from '#lib/workspaces/href.js';
	import { metadataFilterLinks } from './metadata-links.js';

	let { itemId, overview, user, onChanged } = $props<{
		itemId: string;
		overview?: ItemOverview;
		user?: components['schemas']['SessionUserView'] | null;
		onChanged: () => Promise<unknown>;
	}>();

	const labels: Record<ItemSection, MessageKey> = {
		overview: msg('Overview'),
		metadata: msg('Metadata'),
		files: msg('Files'),
		organize: msg('Organize'),
		annotations: msg('Annotations'),
		discussion: msg('Discussion')
	};
	const sectionKeys = Object.keys(labels) as ItemSection[];
	const { workspaceId } = getWorkspaceContext();
	const section = $derived.by(() => {
		const candidate = page.url.pathname.split('/').filter(Boolean)[4];
		return sectionKeys.find((key) => key === candidate) ?? 'overview';
	});
	const title = $derived(overview?.metadata.title);
	const links = $derived(overview && metadataFilterLinks(workspaceId, overview.metadata));

	function sectionPath(key: string) {
		return workspaceHref(
			workspaceId,
			key === 'overview' ? `item/${itemId}` : `item/${itemId}/${key}`
		);
	}
</script>

<div class="mb-6 flex flex-wrap items-end justify-between gap-4">
	<div class="min-w-0">
		<a
			class="mb-2 inline-flex items-center gap-1 text-xs font-bold tracking-[0.1em] text-primary-700-300 uppercase no-underline hover:text-primary-800-200"
			href={resolve(workspaceHref(workspaceId, 'library'))}>{$t('Library')}</a
		>
		<h1 class="max-w-4xl text-balance">
			{#if title}<RichText html={title} />{:else}{$t('Item details')}{/if}
		</h1>
		{#if links}<p class="mt-2 text-sm text-surface-700-300">
				{#each links.authors as author, index (index)}
					{#if index > 0};
					{/if}<a
						href={resolve(author.href)}
						title={$t('View Items by {name}', { name: author.label })}>{author.label}</a
					>
				{:else}{$t('Unknown authors')}{/each}
				{#if links.publication.href}
					· <a
						href={resolve(links.publication.href)}
						title={$t('View Items in {name}', { name: links.publication.label })}
						>{links.publication.label}</a
					>{/if}
				{#if links.date.href}
					· <a
						href={resolve(links.date.href)}
						title={$t('View Items published in {year}', { year: links.date.year })}
						>{links.date.label}</a
					>{/if}
			</p>{/if}
	</div>
	{#if overview && user}{#key itemId}<ItemActions
				{itemId}
				{overview}
				userId={user.id}
				onchanged={onChanged}
			/>{/key}{/if}
</div>
<SectionTabs label={$t('Item sections')}>
	{#each Object.entries(labels) as [key, label] (key)}
		<SectionTab current={section === key} href={resolve(sectionPath(key))}>{$t(label)}</SectionTab>
	{/each}
</SectionTabs>
