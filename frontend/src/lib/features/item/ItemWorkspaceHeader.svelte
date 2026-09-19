<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import type { components } from '$lib/api/schema';
	import RichText from '$lib/design/RichText.svelte';
	import ItemActions from '$lib/features/item/ItemActions.svelte';
	import { msg, t, type MessageKey } from '$lib/i18n';
	import type { ItemSection, ItemWorkspace } from './queries';

	let { itemId, workspace, user, onChanged } = $props<{
		itemId: string;
		workspace?: ItemWorkspace;
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
	const section = $derived.by(() => {
		const candidate = page.url.pathname.split('/').filter(Boolean)[2];
		return sectionKeys.find((key) => key === candidate) ?? 'overview';
	});
	const title = $derived(workspace?.item.title_html);

	function sectionPath(key: string) {
		return key === 'overview' ? (`/item/${itemId}` as const) : (`/item/${itemId}/${key}` as const);
	}
</script>

<div class="mb-6 flex flex-wrap items-end justify-between gap-4">
	<div class="min-w-0">
		<a
			class="mb-2 inline-flex items-center gap-1 text-xs font-bold tracking-[0.1em] text-primary-700-300 uppercase no-underline hover:text-primary-800-200"
			href={resolve('/library')}>{$t('Library')}</a
		>
		<h1 class="max-w-4xl text-balance">
			{#if title}<RichText html={title} />{:else}{$t('Item workspace')}{/if}
		</h1>
		{#if workspace}<p class="mt-2 text-sm text-surface-700-300">
				{workspace.item.authors || $t('Unknown authors')}{#if workspace.item.publication_title}
					· {workspace.item.publication_title}{/if}{#if workspace.item.publication_date}
					· {workspace.item.publication_date}{/if}
			</p>{/if}
	</div>
	{#if workspace && user}{#key itemId}<ItemActions
				{itemId}
				{workspace}
				userId={user.id}
				onchanged={onChanged}
			/>{/key}{/if}
</div>
<nav
	class="mb-6 flex gap-1 overflow-x-auto border-b border-surface-300-700"
	aria-label={$t('Item workspace')}
>
	{#each Object.entries(labels) as [key, label] (key)}
		<a
			class="border-b-2 border-transparent px-3 py-2.5 text-sm font-semibold whitespace-nowrap text-surface-700-300 no-underline transition-colors hover:text-primary-700-300 aria-[current=page]:border-primary-700-300 aria-[current=page]:text-primary-700-300"
			aria-current={section === key ? 'page' : undefined}
			href={resolve(sectionPath(key))}>{$t(label)}</a
		>
	{/each}
</nav>
