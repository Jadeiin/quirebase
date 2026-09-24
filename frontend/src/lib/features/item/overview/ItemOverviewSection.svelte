<script lang="ts">
	import { resolve } from '$app/paths';
	import type { ItemOverviewView } from '$lib/api/client';
	import Panel from '$lib/design/Panel.svelte';
	import RichText from '$lib/design/RichText.svelte';
	import { t } from '$lib/i18n';
	import type { ItemDetail } from '../types';
	import { getWorkspaceContext } from '$lib/workspaces/context.svelte';
	import { workspaceHref } from '$lib/workspaces/href';

	let { itemId, data, details } = $props<{
		itemId: string;
		data: ItemOverviewView;
		details?: ItemDetail;
	}>();

	let imageLoadFailed = $state(false);
	const { workspaceId } = getWorkspaceContext();

	function isSafeExternalUrl(value: string): boolean {
		try {
			const protocol = new URL(value).protocol;
			return protocol === 'http:' || protocol === 'https:';
		} catch {
			return false;
		}
	}

	$effect(() => {
		if (data.thumbnail) {
			imageLoadFailed = false;
		}
	});
</script>

<div class="grid grid-cols-1 items-start gap-5 lg:grid-cols-[minmax(0,1.5fr)_minmax(17rem,0.5fr)]">
	<div class="grid grid-cols-1 gap-3">
		<Panel padding="none">
			<header class="border-b border-surface-300-700 px-5 py-4">
				<h2 class="m-0 text-lg">{$t('Abstract')}</h2>
			</header>
			<div class="px-5 py-5 leading-7 text-surface-700-300">
				{#if details?.abstract_html}
					<RichText html={details.abstract_html} />
				{:else}
					<p class="m-0 text-surface-600-400">{$t('No abstract available.')}</p>
				{/if}
			</div>
		</Panel>
		<Panel padding="none">
			<header class="flex items-center justify-between border-b border-surface-300-700 px-5 py-4">
				<h2 class="m-0 text-lg">{$t('Publication details')}</h2>
				{#if data.allowed_actions.edit}
					<a
						class="text-sm font-semibold text-primary-700-300 no-underline"
						href={resolve(workspaceHref(workspaceId, `item/${itemId}/metadata`))}
						>{$t('Edit metadata')}</a
					>
				{/if}
			</header>
			<dl class="grid grid-cols-1 gap-4 px-5 py-5 text-sm sm:grid-cols-2">
				<div>
					<dt class="text-surface-600-400">{$t('Publication')}</dt>
					<dd class="m-0 mt-1">{data.item.publication_title ?? '—'}</dd>
				</div>
				<div>
					<dt class="text-surface-600-400">{$t('Date')}</dt>
					<dd class="m-0 mt-1">{data.item.publication_date ?? '—'}</dd>
				</div>
				<div>
					<dt class="text-surface-600-400">DOI</dt>
					<dd class="m-0 mt-1 break-all">{data.item.doi ?? '—'}</dd>
				</div>
				<div>
					<dt class="text-surface-600-400">{$t('Type')}</dt>
					<dd class="m-0 mt-1">{details?.metadata.reference_type ?? '—'}</dd>
				</div>
				<div>
					<dt class="text-surface-600-400">{$t('Volume / Issue')}</dt>
					<dd class="m-0 mt-1">
						{details?.metadata.volume ?? '—'} / {details?.metadata.issue ?? '—'}
					</dd>
				</div>
				<div>
					<dt class="text-surface-600-400">{$t('Pages')}</dt>
					<dd class="m-0 mt-1">{details?.metadata.pages ?? '—'}</dd>
				</div>
				<div>
					<dt class="text-surface-600-400">{$t('Journal abbreviation')}</dt>
					<dd class="m-0 mt-1">{details?.metadata.journal_abbreviation ?? '—'}</dd>
				</div>
				<div>
					<dt class="text-surface-600-400">{$t('Publisher')}</dt>
					<dd class="m-0 mt-1">
						{details?.metadata.publisher ?? '—'}{#if details?.metadata.place_published}
							· {details.metadata.place_published}{/if}
					</dd>
				</div>
				<div class="sm:col-span-2">
					<dt class="text-surface-600-400">{$t('Affiliation')}</dt>
					<dd class="m-0 mt-1">{details?.metadata.affiliation ?? '—'}</dd>
				</div>
			</dl>
			<div class="grid grid-cols-4 border-t border-surface-300-700 bg-surface-100-900">
				<div class="grid grid-cols-1 gap-0.5 border-r border-surface-300-700 p-4">
					<strong class="text-2xl tabular-nums">{data.counts.revisions}</strong><span
						class="text-xs text-surface-600-400">{$t('PDF revisions')}</span
					>
				</div>
				<div class="grid grid-cols-1 gap-0.5 border-r border-surface-300-700 p-4">
					<strong class="text-2xl tabular-nums">{data.counts.attachments}</strong><span
						class="text-xs text-surface-600-400">{$t('Supplements')}</span
					>
				</div>
				<div class="grid grid-cols-1 gap-0.5 border-r border-surface-300-700 p-4">
					<strong class="text-2xl tabular-nums">{data.counts.annotations}</strong><span
						class="text-xs text-surface-600-400">{$t('Annotations')}</span
					>
				</div>
				<div class="grid grid-cols-1 gap-0.5 p-4">
					<strong class="text-2xl tabular-nums">{data.counts.discussion}</strong><span
						class="text-xs text-surface-600-400">{$t('Messages')}</span
					>
				</div>
			</div>
		</Panel>
	</div>
	<aside class="grid grid-cols-1 content-start gap-5">
		{#if data.thumbnail && !imageLoadFailed}
			<Panel padding="sm">
				<a
					class="group block overflow-hidden rounded-lg bg-surface-100-900 transition hover:opacity-95 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-500"
					href={data.thumbnail.source_kind === 'pdf_thumbnail'
						? resolve(workspaceHref(workspaceId, `item/${itemId}/pdf/${data.thumbnail.source_id}`))
						: resolve(workspaceHref(workspaceId, `item/${itemId}/files`))}
					aria-label={$t('Item thumbnail')}
				>
					<img
						class="block max-h-80 w-full rounded-md bg-white object-contain transition-transform duration-200 group-hover:scale-[1.01] dark:bg-surface-950"
						src={`/api/v1/workspaces/${encodeURIComponent(workspaceId)}/items/${encodeURIComponent(itemId)}/thumbnail?source=${encodeURIComponent(data.thumbnail.source_id)}`}
						alt={$t('Item thumbnail')}
						loading="lazy"
						onerror={() => {
							imageLoadFailed = true;
						}}
					/>
				</a>
			</Panel>
		{/if}
		<Panel>
			<h2 class="m-0 mb-4 text-lg">{$t('Tags')}</h2>
			<div class="flex flex-wrap gap-2">
				{#each data.tags as tag (tag.id)}
					<span
						class="rounded-full bg-primary-50-950 px-2.5 py-1 text-xs font-semibold text-primary-800-200"
						>{tag.name}</span
					>
				{:else}
					<span class="text-sm text-surface-600-400">{$t('No tags')}</span>
				{/each}
			</div>
		</Panel>
		<Panel>
			<h2 class="m-0 mb-4 text-lg">{$t('Keywords')}</h2>
			<div class="flex flex-wrap gap-2">
				{#each details?.metadata.keywords ?? [] as keyword (keyword)}
					<span
						class="rounded-full border border-surface-300-700 bg-surface-200-800 px-2.5 py-1 text-xs font-semibold"
						>{keyword}</span
					>
				{:else}
					<span class="text-sm text-surface-600-400">{$t('No keywords.')}</span>
				{/each}
			</div>
		</Panel>
		<Panel>
			<h2 class="m-0 mb-4 text-lg">{$t('External links')}</h2>
			<div class="grid grid-cols-1 gap-2">
				{#each details?.metadata.urls ?? [] as url, index (url)}
					{#if isSafeExternalUrl(url)}
						<a
							class="grid min-w-0 grid-cols-1 gap-0.5 rounded-lg border border-surface-300-700 px-3 py-2 text-sm no-underline hover:bg-primary-50-950"
							href={url}
							target="_blank"
							rel="external noreferrer"
							><strong>{$t('External source {number}', { number: index + 1 })}</strong><span
								class="truncate text-xs text-surface-600-400">{url}</span
							></a
						>
					{:else}
						<span
							class="grid min-w-0 grid-cols-1 gap-0.5 rounded-lg border border-surface-300-700 px-3 py-2 text-sm"
							><strong>{$t('External source {number}', { number: index + 1 })}</strong><span
								class="truncate text-xs text-surface-600-400">{url}</span
							></span
						>
					{/if}
				{:else}
					<span class="text-sm text-surface-600-400">{$t('No external links.')}</span>
				{/each}
			</div>
		</Panel>
		<Panel>
			<h2 class="m-0 mb-4 text-lg">{$t('Record')}</h2>
			<dl class="grid grid-cols-1 gap-3 text-sm">
				<div>
					<dt class="text-surface-600-400">{$t('Permissions')}</dt>
					<dd class="m-0">{data.allowed_actions.edit ? $t('Can edit') : $t('Read only')}</dd>
				</div>
				<div>
					<dt class="text-surface-600-400">{$t('Citation key')}</dt>
					<dd class="m-0"><code>{details?.metadata.bibtex_key ?? '—'}</code></dd>
				</div>
			</dl>
		</Panel>
	</aside>
</div>
