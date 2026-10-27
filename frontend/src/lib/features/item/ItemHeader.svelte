<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import type { components } from '#lib/api/schema.js';
	import SectionTabs from '#lib/design/SectionTabs.svelte';
	import SectionTab from '#lib/design/SectionTab.svelte';
	import Icon from '#lib/design/Icon.svelte';
	import RichText from '#lib/design/RichText.svelte';
	import ItemActions from '#lib/features/item/ItemActions.svelte';
	import { msg, ph, t } from 'lingui-for-svelte/macro';
	import type { MessageDescriptor } from '@lingui/core';
	import type { ItemOverview, ItemSection } from './queries';
	import { getWorkspaceContext } from '#lib/workspaces/context.svelte.js';
	import { metadataFilterLinks } from './metadata-links.js';
	import {
		libraryItemHref,
		libraryReturnHref,
		readLibraryReturnTo
	} from '#lib/features/library/return-context.js';

	let {
		itemId,
		overview,
		user,
		onChanged
	}: {
		itemId: string;
		overview?: ItemOverview;
		user?: components['schemas']['SessionUserView'] | null;
		onChanged: () => Promise<unknown>;
	} = $props();

	const labels: Record<ItemSection, MessageDescriptor> = {
		overview: msg`Overview`,
		metadata: msg`Metadata`,
		files: msg`Files`,
		organize: msg`Organize`,
		annotations: msg`Annotations`,
		discussion: msg`Discussion`
	};
	const sectionKeys = Object.keys(labels) as ItemSection[];
	const { workspaceId } = getWorkspaceContext();
	const section = $derived.by(() => {
		const candidate = page.url.pathname.split('/').filter(Boolean)[4];
		return sectionKeys.find((key) => key === candidate) ?? 'overview';
	});
	const title = $derived(overview?.metadata.title);
	const links = $derived(overview && metadataFilterLinks(workspaceId, overview.metadata));
	const returnTo = $derived(readLibraryReturnTo(workspaceId, page.url.searchParams));

	function sectionPath(key: string) {
		return libraryItemHref(workspaceId, itemId, key === 'overview' ? '' : key, returnTo);
	}
</script>

<header class="mb-5 w-full min-w-0">
	<a
		class="mb-3 inline-flex items-center gap-1 text-sm font-medium text-primary-700-300 no-underline hover:text-primary-800-200"
		href={resolve(libraryReturnHref(workspaceId, page.url.searchParams))}
		><Icon name="chevron-left" size={16} />{$t`Library`}</a
	>
	<h1 class="m-0 wrap-anywhere">
		{#if title}<RichText html={title} />{:else}{$t`Item details`}{/if}
	</h1>
	{#if links}
		<div class="mt-3 space-y-1 text-sm leading-relaxed wrap-anywhere">
			<p class="m-0 text-surface-700-300">
				{#each links.authors as author, index (index)}
					{index > 0 ? '; ' : ''}<a
						class="underline-offset-4 hover:text-primary-700-300 hover:underline"
						href={resolve(author.href)}
						title={$t`View Items by ${ph({ name: author.label })}`}>{author.label}</a
					>
				{:else}{$t`Unknown authors`}{/each}
			</p>
			{#if links.publication.href || links.date.href}
				<p class="m-0 text-surface-600-400">
					{#if links.publication.href}
						<a
							class="underline-offset-4 hover:text-primary-700-300 hover:underline"
							href={resolve(links.publication.href)}
							title={$t`View Items in ${ph({ name: links.publication.label })}`}
							>{links.publication.label}</a
						>
					{/if}
					{#if links.date.href}
						<span class="whitespace-nowrap">
							{#if links.publication.href}<span aria-hidden="true"> · </span>{/if}
							<a
								class="underline-offset-4 hover:text-primary-700-300 hover:underline"
								href={resolve(links.date.href)}
								title={$t`View Items published in ${ph({ year: links.date.year })}`}
								>{links.date.label}</a
							>
						</span>
					{/if}
				</p>
			{/if}
		</div>
	{/if}
	{#if overview && user}
		<div class="mt-4">
			{#key itemId}
				<ItemActions {itemId} {overview} userId={user.id} onchanged={onChanged} />
			{/key}
		</div>
	{/if}
</header>
<SectionTabs label={$t`Item sections`}>
	{#each Object.entries(labels) as [key, label] (key)}
		<SectionTab current={section === key} href={resolve(sectionPath(key))}>{$t(label)}</SectionTab>
	{/each}
</SectionTabs>
