<script lang="ts">
	import { pdfFileUrls, type Metadata } from '../metadata-draft.js';
	import SearchSelect from '#lib/design/SearchSelect.svelte';
	import { resolve } from '$app/paths';
	import { domainLabel } from '#lib/domain-labels.js';
	import { kilobytes, numberFormat } from '#lib/format.js';
	import Panel from '#lib/design/Panel.svelte';
	import { t } from '#lib/i18n.js';
	import type { FileRow, FilesView } from '../types';
	import Button from '#lib/design/Button.svelte';
	import ItemRow from '#lib/design/ItemRow.svelte';
	import { getWorkspaceContext } from '#lib/workspaces/context.svelte.js';
	import { workspaceHref } from '#lib/workspaces/href.js';

	let {
		itemId,
		data,
		metadata,
		canEdit,
		canDelete,
		busy,
		onUpload,
		onUploadFromUrl,
		onDownload,
		onDelete
	} = $props<{
		itemId: string;
		data: FilesView;
		metadata: Metadata;
		canEdit: boolean;
		canDelete: boolean;
		busy: boolean;
		onUpload: (event: SubmitEvent, kind: 'revision' | 'attachment') => void;
		onUploadFromUrl: (event: SubmitEvent, kind: 'revision' | 'attachment') => void;
		onDownload: (file: FileRow) => void;
		onDelete: (file: FileRow) => void;
	}>();
	const workspace = getWorkspaceContext();
	const { workspaceId } = workspace;
	const pdfOptions = $derived(pdfFileUrls(metadata).map((url) => ({ value: url, label: url })));
	let pdfUrl = $state<string | undefined>(undefined);
	let pdfSearch = $state<string | null>(null);
	let draftItemId = $state<string | undefined>(undefined);
	$effect(() => {
		if (draftItemId === itemId) return;
		draftItemId = itemId;
		pdfUrl = undefined;
		pdfSearch = null;
	});
</script>

<div class="grid grid-cols-1 gap-4 min-[800px]:grid-cols-[minmax(0,2fr)_minmax(16rem,1fr)]">
	<Panel class="mt-4">
		<h2>{$t('Files')}</h2>
		{#each data.files as file (file.id)}
			<ItemRow class="grid-cols-[minmax(0,1fr)_auto] items-center">
				<div class="grid grid-cols-1 gap-1">
					<strong>{file.original_name}</strong><span class="text-surface-600-400"
						>{$t('{kind} · {size} KB', {
							kind: $t(domainLabel(file.kind)),
							size: $numberFormat.format(kilobytes(file.size))
						})}{file.processing_state ? ` · ${$t(domainLabel(file.processing_state))}` : ''}</span
					>
				</div>
				<div class="flex flex-wrap gap-2">
					{#if file.kind === 'revision' && file.processing_state === 'ready'}
						<Button
							as="a"
							href={resolve(workspaceHref(workspaceId, `item/${itemId}/pdf/${file.id}`))}
							>{$t('Read')}</Button
						>
					{/if}
					{#if workspace.can('workspace.export')}<Button onclick={() => onDownload(file)}
							>{$t('Download')}</Button
						>{/if}
					{#if canDelete}
						<Button variant="danger" disabled={busy} onclick={() => onDelete(file)}
							>{$t('Delete')}</Button
						>
					{/if}
				</div>
			</ItemRow>
		{:else}
			<p class="text-surface-600-400">{$t('No files.')}</p>
		{/each}
	</Panel>
	{#if canEdit}
		<aside class="grid grid-cols-1 gap-3">
			<Panel
				as="form"
				class="grid grid-cols-1 gap-3"
				onsubmit={(event) => onUpload(event, 'revision')}
			>
				<h2>{$t('Add PDF revision')}</h2>
				<input
					class="input"
					name="pdf"
					type="file"
					accept="application/pdf,.pdf"
					disabled={busy}
					required
				/><Button disabled={busy}>{$t('Upload PDF')}</Button>
			</Panel>
			<Panel
				as="form"
				class="grid grid-cols-1 gap-3"
				onsubmit={(event) => onUploadFromUrl(event, 'revision')}
				onreset={() => {
					pdfUrl = '';
					pdfSearch = null;
				}}
			>
				<h2>{$t('Add a PDF from URL')}</h2>
				<SearchSelect
					label={$t('PDF URL')}
					inputName="url"
					inputType="url"
					allowCustomValue
					required
					disabled={busy}
					bind:value={() => pdfUrl ?? pdfOptions[0]?.value ?? '', (next) => (pdfUrl = next)}
					bind:search={pdfSearch}
					options={pdfOptions}
					placeholder="https://example.org/article.pdf"
				/><Button disabled={busy}>{$t('Download and add PDF')}</Button>
			</Panel>
			<Panel
				as="form"
				class="grid grid-cols-1 gap-3"
				onsubmit={(event) => onUpload(event, 'attachment')}
			>
				<h2>{$t('Add attachment')}</h2>
				<input class="input" name="attachment" type="file" disabled={busy} required />
				<label class="flex items-center gap-2"
					><input name="graphical_abstract" type="checkbox" value="true" disabled={busy} />
					{$t('Use as Graphical Abstract')}</label
				>
				<Button disabled={busy}>{$t('Upload attachment')}</Button>
			</Panel>
			<Panel
				as="form"
				class="grid grid-cols-1 gap-3"
				onsubmit={(event) => onUploadFromUrl(event, 'attachment')}
			>
				<h2>{$t('Add attachment from URL')}</h2>
				<input
					class="input"
					name="url"
					type="url"
					disabled={busy}
					placeholder="https://example.org/supplement.zip"
					required
				/>
				<label class="flex items-center gap-2"
					><input name="graphical_abstract" type="checkbox" value="true" disabled={busy} />
					{$t('Use as Graphical Abstract')}</label
				>
				<Button disabled={busy}>{$t('Download and add attachment')}</Button>
			</Panel>
		</aside>
	{/if}
</div>
