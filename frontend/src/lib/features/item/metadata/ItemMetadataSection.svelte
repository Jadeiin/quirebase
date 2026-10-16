<script lang="ts">
	import type { components } from '#lib/api/schema.js';
	import Button from '#lib/design/Button.svelte';
	import Notice from '#lib/design/Notice.svelte';
	import Panel from '#lib/design/Panel.svelte';
	import RichText from '#lib/design/RichText.svelte';
	import ItemMetadataForm from '#lib/features/item/ItemMetadataForm.svelte';
	import {
		objects,
		object,
		text,
		contributorName,
		workKeywords,
		identifierRows,
		type Metadata
	} from '../metadata-draft.js';
	import { t } from '#lib/i18n.js';
	import type { ItemDetail } from '../types';
	let {
		item,
		canEdit,
		busy,
		onSubmit,
		serverErrors = []
	} = $props<{
		item: ItemDetail;
		canEdit: boolean;
		busy: boolean;
		serverErrors?: components['schemas']['ErrorField'][];
		onSubmit: (item: ItemDetail, metadata: Metadata, citationKey: string) => Promise<boolean>;
	}>();
	// svelte-ignore state_referenced_locally
	let editingItem = $state(structuredClone($state.snapshot(item)));
	let editorRevision = $state(0);
	let dirty = $state(false);
	$effect(() => {
		if (item.id !== editingItem.id || (item.version !== editingItem.version && !dirty && !busy))
			loadLatest();
	});
	const stale = $derived(item.id !== editingItem.id || item.version !== editingItem.version);
	function loadLatest() {
		editingItem = structuredClone($state.snapshot(item));
		editorRevision += 1;
		dirty = false;
	}
	async function save(metadata: Metadata, citationKey: string) {
		if (stale) return;
		const snapshot = $state.snapshot(editingItem);
		if ((await onSubmit(snapshot, metadata, citationKey)) && item.id === snapshot.id) loadLatest();
	}
</script>

<Panel class="grid grid-cols-1 gap-3">
	<h2>{$t('Metadata')}</h2>
	{#if canEdit}
		{#if stale}
			<Notice variant="warning"
				>{$t(
					'This Item has changed. Your draft is preserved. Review the latest metadata before retrying.'
				)}</Notice
			>
			<details>
				<summary>{$t('Latest saved metadata')}</summary>
				<pre class="max-h-80 overflow-auto text-sm">{JSON.stringify(item.metadata, null, 2)}</pre>
			</details>
			<div class="flex flex-wrap gap-2">
				<Button
					onclick={() => {
						editingItem = structuredClone($state.snapshot(item));
					}}>{$t('Use latest version and keep draft')}</Button
				>
				<Button onclick={loadLatest}>{$t('Discard draft and load latest')}</Button>
			</div>
		{/if}
		{#key `${editingItem.id}:${editorRevision}`}
			<ItemMetadataForm
				metadata={editingItem.metadata}
				citationKey={editingItem.citation_key ?? ''}
				busy={busy || stale}
				submitLabel={$t('Save metadata')}
				{serverErrors}
				onsubmit={save}
				ondirty={(changed) => (dirty = changed)}
			/>
		{/key}
	{:else}
		<RichText html={item.metadata.title} />
		<dl class="grid grid-cols-1 gap-4 text-sm sm:grid-cols-2">
			<div>
				<dt>{$t('Authors')}</dt>
				<dd>
					{objects(item.metadata.contributors)
						.filter((row) => Array.isArray(row.roles) && row.roles.includes('Author'))
						.map(contributorName)
						.join('; ') || '—'}
				</dd>
			</div>
			<div>
				<dt>{$t('Editors')}</dt>
				<dd>
					{objects(item.metadata.contributors)
						.filter((row) => Array.isArray(row.roles) && row.roles.includes('Editor'))
						.map(contributorName)
						.join('; ') || '—'}
				</dd>
			</div>
			<div>
				<dt>{$t('Publication')}</dt>
				<dd>{text(object(item.metadata.container).title) || '—'}</dd>
			</div>
			<div>
				<dt>{$t('Publication date')}</dt>
				<dd>{text(item.metadata.date_published) || '—'}</dd>
			</div>
			<div>
				<dt>{$t('Reference type')}</dt>
				<dd>{text(item.metadata.type)}</dd>
			</div>
			<div>
				<dt>{$t('Citation key')}</dt>
				<dd>{item.citation_key || '—'}</dd>
			</div>
			<div>
				<dt>{$t('Keywords')}</dt>
				<dd>{workKeywords(item.metadata).join('; ') || '—'}</dd>
			</div>
			<div>
				<dt>{$t('Upstream identifiers')}</dt>
				<dd>
					{text(item.metadata.id)}{#each identifierRows(item.metadata) as row, index (index)}<div>
							{row.namespace}: {row.value}
						</div>{/each}
				</dd>
			</div>
		</dl>
		{#if item.metadata.description}<RichText html={item.metadata.description} />{/if}
	{/if}
</Panel>
