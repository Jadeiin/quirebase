<script lang="ts">
	import { resolve } from '$app/paths';
	import { domainLabel } from '$lib/domain-labels';
	import { kilobytes, numberFormat } from '$lib/format';
	import Panel from '$lib/design/Panel.svelte';
	import { t } from '$lib/i18n';
	import type { FileRow, FilesView, ItemDetail } from '../types';
	import Button from '$lib/design/Button.svelte';
	import ItemRow from '$lib/design/ItemRow.svelte';

	let { itemId, data, details, canEdit, busy, onUpload, onUploadFromUrl, onDownload, onDelete } =
		$props<{
			itemId: string;
			data: FilesView;
			details?: ItemDetail;
			canEdit: boolean;
			busy: boolean;
			onUpload: (event: SubmitEvent, kind: 'revision' | 'attachment') => void;
			onUploadFromUrl: (event: SubmitEvent, kind: 'revision' | 'attachment') => void;
			onDownload: (file: FileRow) => void;
			onDelete: (file: FileRow) => void;
		}>();
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
							href={resolve('/(app)/item/[itemId]/pdf/[revisionId]', {
								itemId,
								revisionId: file.id
							})}>{$t('Read')}</Button
						>
					{/if}
					<Button onclick={() => onDownload(file)}>{$t('Download')}</Button>
					{#if canEdit}
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
			>
				<h2>{$t('Add a PDF from URL')}</h2>
				<input
					class="input"
					name="url"
					type="url"
					disabled={busy}
					value={details?.metadata.urls.find((url: string) => url.toLowerCase().includes('.pdf')) ??
						''}
					placeholder="https://example.org/article.pdf"
					required
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
