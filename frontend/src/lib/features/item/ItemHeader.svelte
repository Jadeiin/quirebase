<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import type { components } from '$lib/api/schema';
	import RichText from '$lib/design/RichText.svelte';
	import ItemActions from '$lib/features/item/ItemActions.svelte';
	import { msg, t, type MessageKey } from '$lib/i18n';
	import type { ItemOverview, ItemSection } from './queries';
	import { getWorkspaceContext } from '$lib/workspaces/context.svelte';
	import { workspaceHref } from '$lib/workspaces/href';

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
	const title = $derived(overview?.item.title_html);

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
		{#if overview}<p class="mt-2 text-sm text-surface-700-300">
				{overview.item.authors || $t('Unknown authors')}{#if overview.item.publication_title}
					· {overview.item.publication_title}{/if}{#if overview.item.publication_date}
					· {overview.item.publication_date}{/if}
			</p>{/if}
	</div>
	{#if overview && user}{#key itemId}<ItemActions
				{itemId}
				{overview}
				userId={user.id}
				onchanged={onChanged}
			/>{/key}{/if}
</div>
<nav
	class="mb-6 flex gap-1 overflow-x-auto border-b border-surface-300-700"
	aria-label={$t('Item sections')}
>
	{#each Object.entries(labels) as [key, label] (key)}
		<a
			class="border-b-2 border-transparent px-3 py-2.5 text-sm font-semibold whitespace-nowrap text-surface-700-300 no-underline transition-colors hover:text-primary-700-300 aria-[current=page]:border-primary-700-300 aria-[current=page]:text-primary-700-300"
			aria-current={section === key ? 'page' : undefined}
			href={resolve(sectionPath(key))}>{$t(label)}</a
		>
	{/each}
</nav>
