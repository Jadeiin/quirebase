<script lang="ts">
	import type { components } from '#lib/api/schema.js';
	import Panel from '#lib/design/Panel.svelte';
	import RichText from '#lib/design/RichText.svelte';
	import ItemMetadataForm from '#lib/features/item/ItemMetadataForm.svelte';
	import { contributorAffiliations } from '../metadata-draft.js';
	import { t } from '#lib/i18n.js';
	import type { ItemDetail } from '../types';

	let { item, canEdit, busy, onSubmit } = $props<{
		item: ItemDetail;
		canEdit: boolean;
		busy: boolean;
		onSubmit: (
			item: ItemDetail,
			metadata: components['schemas']['BibliographicMetadata-Input']
		) => void;
	}>();
</script>

<Panel class="grid grid-cols-1 gap-3">
	<h2>{$t('Metadata')}</h2>
	{#if canEdit}
		{#key `${item.id}:${item.version}`}
			<ItemMetadataForm
				metadata={item.metadata}
				{busy}
				submitLabel={$t('Save metadata')}
				onsubmit={(metadata) => onSubmit(item, metadata)}
			/>
		{/key}
	{:else}
		<dl class="grid grid-cols-1 gap-4 text-sm sm:grid-cols-2">
			<div class="sm:col-span-2">
				<dt class="text-surface-600-400">{$t('Title')}</dt>
				<dd class="m-0 mt-1"><RichText html={item.title_html} /></dd>
			</div>
			<div>
				<dt class="text-surface-600-400">{$t('Authors')}</dt>
				<dd class="m-0 mt-1">
					{item.metadata.authors
						.map((author: components['schemas']['Contributor']) => author.display_name)
						.join('; ') || '—'}
				</dd>
			</div>
			<div>
				<dt class="text-surface-600-400">{$t('Editors')}</dt>
				<dd class="m-0 mt-1">
					{item.metadata.editors
						.map((editor: components['schemas']['Contributor']) => editor.display_name)
						.join('; ') || '—'}
				</dd>
			</div>
			{#each [[$t('Publication'), item.metadata.publication_title], [$t('Publication date'), item.metadata.publication_date], [$t('Reference type'), item.metadata.reference_type], [$t('Volume'), item.metadata.volume], [$t('Issue'), item.metadata.issue], [$t('Pages'), item.metadata.pages], [$t('Publisher'), item.metadata.publisher], [$t('Affiliation'), contributorAffiliations(item.metadata).join('; ')], [$t('Citation key'), item.metadata.citation_key]] as field (field[0])}
				<div>
					<dt class="text-surface-600-400">{field[0]}</dt>
					<dd class="m-0 mt-1">{field[1] || '—'}</dd>
				</div>
			{/each}
			<div class="sm:col-span-2">
				<dt class="text-surface-600-400">{$t('Upstream identifiers')}</dt>
				<dd class="m-0 mt-1">
					{#if item.metadata.identifiers.length}
						<ul class="list-none space-y-1 p-0">
							{#each item.metadata.identifiers as identifier (identifier.provider)}
								<li><strong>{identifier.provider.toUpperCase()}</strong>: {identifier.value}</li>
							{/each}
						</ul>
					{:else}—{/if}
				</dd>
			</div>
			<div class="sm:col-span-2">
				<dt class="text-surface-600-400">{$t('Keywords')}</dt>
				<dd class="m-0 mt-1">{item.metadata.keywords.join('; ') || '—'}</dd>
			</div>
			<div class="sm:col-span-2">
				<dt class="text-surface-600-400">{$t('Abstract')}</dt>
				<dd class="m-0 mt-1 whitespace-pre-wrap">
					{#if item.abstract_html}<RichText html={item.abstract_html} />{:else}—{/if}
				</dd>
			</div>
		</dl>
	{/if}
</Panel>
