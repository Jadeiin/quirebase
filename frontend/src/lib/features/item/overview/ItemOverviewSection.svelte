<script lang="ts">
	import { resolve } from '$app/paths';
	import type { ItemOverviewView } from '#lib/api/client.js';
	import { can } from '#lib/authorization/can.js';
	import Panel from '#lib/design/Panel.svelte';
	import RichText from '#lib/design/RichText.svelte';
	import { t, activeLocale } from '#lib/i18n.js';
	import { metadataValueLabel } from '../metadata-labels.js';
	import {
		contributorAffiliations,
		identifierRows,
		object,
		objects,
		text,
		workKeywords
	} from '../metadata-draft.js';
	import { getWorkspaceContext } from '#lib/workspaces/context.svelte.js';
	import { workspaceHref } from '#lib/workspaces/href.js';
	import { libraryHref } from '#lib/features/library/filters.js';
	import { metadataFilterLinks } from '../metadata-links.js';

	let { itemId, data } = $props<{
		itemId: string;
		data: ItemOverviewView;
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

	const container = $derived(object(data.metadata.container));
	const links = $derived(metadataFilterLinks(workspaceId, data.metadata));
	const externalUrls = $derived([
		...new Set(
			[
				text(data.metadata.url),
				...objects(data.metadata.files).map((file) => text(file.url))
			].filter(Boolean)
		)
	]);
	const publicationRows = $derived.by(() => {
		void $activeLocale;
		const publisher = object(data.metadata.publisher);
		const host = object(container.publisher);
		const license = object(container.license);
		const pages = [
			...new Set([text(container.first_page), text(container.last_page)].filter(Boolean))
		].join('–');
		return [
			{
				label: $t('Publication'),
				value: links.publication.label || '—',
				internalHref: links.publication.href,
				hint: $t('View Items in {name}', { name: links.publication.label })
			},
			{
				label: $t('Date'),
				value: links.date.label || '—',
				internalHref: links.date.href,
				hint: $t('View Items published in {year}', { year: links.date.year })
			},
			{
				label: $t('Upstream identifiers'),
				value:
					[
						text(data.metadata.id),
						...identifierRows(data.metadata).map((row) => `${row.namespace}: ${row.value}`)
					]
						.filter(Boolean)
						.join('; ') || '—'
			},
			{
				label: $t('Type'),
				value: metadataValueLabel(links.type.value) || '—',
				internalHref: links.type.href,
				hint: $t('View Items of type {name}', { name: metadataValueLabel(links.type.value) })
			},
			{
				label: $t('Volume / Issue'),
				value: `${text(container.volume) || '—'} / ${text(container.issue) || '—'}`
			},
			{ label: $t('Pages'), value: pages || '—' },
			{
				label: $t('Publisher'),
				value: text(publisher.name) || text(publisher.id) || '—',
				href: text(publisher.id)
			},
			{ label: $t('Publication type'), value: metadataValueLabel(text(container.type)) },
			{
				label: $t('Additional titles'),
				value: Array.isArray(container.additional_titles)
					? container.additional_titles.map(text).filter(Boolean).join('; ')
					: ''
			},
			{
				label: $t('Publication publisher'),
				value: text(host.name) || text(host.id),
				href: text(host.id)
			},
			{
				label: $t('Publication identifiers'),
				value: objects(container.identifiers)
					.map((row) => `${text(row.identifier_type)}: ${text(row.identifier)}`)
					.join('; ')
			},
			{ label: $t('Platform'), value: text(container.platform) },
			{ label: $t('Series'), value: text(container.series) },
			{ label: $t('Location'), value: text(container.location) },
			{ label: $t('Country'), value: text(container.country) },
			{ label: $t('Language'), value: text(container.language) },
			{
				label: $t('License'),
				value: text(license.title) || text(license.id) || text(license.url),
				href: text(license.id) || text(license.url)
			},
			{ label: $t('URL'), value: text(container.url), href: text(container.url) },
			{ label: $t('Updated date'), value: text(container.date_updated) },
			{ label: $t('Description'), value: text(container.description) }
		].filter((row) => row.value);
	});

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
				{#if data.metadata.description}
					<RichText html={data.metadata.description} />
				{:else}
					<p class="m-0 text-surface-600-400">{$t('No abstract available.')}</p>
				{/if}
			</div>
		</Panel>
		<Panel padding="none">
			<header class="flex items-center justify-between border-b border-surface-300-700 px-5 py-4">
				<h2 class="m-0 text-lg">{$t('Publication details')}</h2>
				{#if can(data.authorization, 'item.update')}
					<a
						class="text-sm font-semibold text-primary-700-300 no-underline"
						href={resolve(workspaceHref(workspaceId, `item/${itemId}/metadata`))}
						>{$t('Edit metadata')}</a
					>
				{/if}
			</header>
			<dl class="grid grid-cols-1 gap-4 px-5 py-5 text-sm sm:grid-cols-2">
				{#each publicationRows as row (row.label)}
					<div class="min-w-0">
						<dt class="text-surface-600-400">{row.label}</dt>
						<dd class="m-0 mt-1 break-words">
							{#if row.internalHref}
								<a href={resolve(row.internalHref)} title={row.hint}>{row.value}</a>
							{:else if row.href && isSafeExternalUrl(row.href)}
								<a href={row.href} target="_blank" rel="external noreferrer">{row.value}</a>
							{:else}{row.value}{/if}
						</dd>
					</div>
				{/each}
				<div class="sm:col-span-2">
					<dt class="text-surface-600-400">{$t('Affiliation')}</dt>
					<dd class="m-0 mt-1">
						{contributorAffiliations(data.metadata).join('; ') || '—'}
					</dd>
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
					<a
						href={resolve(libraryHref(workspaceId, { tag: tag.id }))}
						title={$t('View Items tagged {name}', { name: tag.name })}
						class="rounded-full bg-primary-50-950 px-2.5 py-1 text-xs font-semibold text-primary-800-200"
						>{tag.name}</a
					>
				{:else}
					<span class="text-sm text-surface-600-400">{$t('No tags')}</span>
				{/each}
			</div>
		</Panel>
		<Panel>
			<h2 class="m-0 mb-4 text-lg">{$t('Keywords')}</h2>
			<div class="flex flex-wrap gap-2">
				{#each workKeywords(data.metadata) as keyword (keyword)}
					<a
						href={resolve(libraryHref(workspaceId, { keyword_exact: keyword }))}
						title={$t('View Items with keyword {name}', { name: keyword })}
						class="rounded-full border border-surface-300-700 bg-surface-200-800 px-2.5 py-1 text-xs font-semibold"
						>{keyword}</a
					>
				{:else}
					<span class="text-sm text-surface-600-400">{$t('No keywords.')}</span>
				{/each}
			</div>
		</Panel>
		<Panel>
			<h2 class="m-0 mb-4 text-lg">{$t('External links')}</h2>
			<div class="grid grid-cols-1 gap-2">
				{#each externalUrls as url, index (url)}
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
					<dd class="m-0">
						{can(data.authorization, 'item.update') ? $t('Can edit') : $t('Read only')}
					</dd>
				</div>
				<div>
					<dt class="text-surface-600-400">{$t('Citation key')}</dt>
					<dd class="m-0"><code>{data.citation_key ?? '—'}</code></dd>
				</div>
			</dl>
		</Panel>
	</aside>
</div>
