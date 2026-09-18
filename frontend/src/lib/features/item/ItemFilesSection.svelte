<script lang="ts">
	import { resolve } from '$app/paths';
	import { domainLabel } from '$lib/domain-labels';
	import { t } from '$lib/i18n';
	import type { FileRow, FilesView, ItemDetail } from './types';

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

<div class="item-layout">
	<section class="list-panel card border border-surface-300-700 bg-surface-50-950 p-5 shadow-sm">
		<h2>{$t('Files')}</h2>
		{#each data.files as file (file.id)}
			<div class="item-row grid-cols-[minmax(0,1fr)_auto] items-center">
				<div class="grid gap-1">
					<strong>{file.original_name}</strong><span class="text-surface-600-400"
						>{$t(domainLabel(file.kind))} · {Math.ceil(file.size / 1024)} KB{file.processing_state
							? ` · ${$t(domainLabel(file.processing_state))}`
							: ''}</span
					>
				</div>
				<div class="toolbar">
					{#if file.kind === 'revision' && file.processing_state === 'ready'}
						<a
							class="btn preset-tonal-surface font-semibold"
							href={resolve('/(app)/item/[itemId]/pdf/[revisionId]', {
								itemId,
								revisionId: file.id
							})}>{$t('Read')}</a
						>
					{/if}
					<button class="btn preset-tonal-surface font-semibold" onclick={() => onDownload(file)}
						>{$t('Download')}</button
					>
					{#if canEdit}
						<button
							class="btn preset-tonal-error font-semibold"
							disabled={busy}
							onclick={() => onDelete(file)}>{$t('Delete')}</button
						>
					{/if}
				</div>
			</div>
		{:else}
			<p class="text-surface-600-400">{$t('No files.')}</p>
		{/each}
	</section>
	{#if canEdit}
		<aside class="stack">
			<form
				class="stack card border border-surface-300-700 bg-surface-50-950 p-5 shadow-sm"
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
				/><button class="btn preset-tonal-surface font-semibold" disabled={busy}
					>{$t('Upload PDF')}</button
				>
			</form>
			<form
				class="stack card border border-surface-300-700 bg-surface-50-950 p-5 shadow-sm"
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
				/><button class="btn preset-tonal-surface font-semibold" disabled={busy}
					>{$t('Download and add PDF')}</button
				>
			</form>
			<form
				class="stack card border border-surface-300-700 bg-surface-50-950 p-5 shadow-sm"
				onsubmit={(event) => onUpload(event, 'attachment')}
			>
				<h2>{$t('Add attachment')}</h2>
				<input class="input" name="attachment" type="file" disabled={busy} required />
				<label class="flex items-center gap-2"
					><input name="graphical_abstract" type="checkbox" value="true" disabled={busy} />
					{$t('Use as Graphical Abstract')}</label
				>
				<button class="btn preset-tonal-surface font-semibold" disabled={busy}
					>{$t('Upload attachment')}</button
				>
			</form>
			<form
				class="stack card border border-surface-300-700 bg-surface-50-950 p-5 shadow-sm"
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
				<button class="btn preset-tonal-surface font-semibold" disabled={busy}
					>{$t('Download and add attachment')}</button
				>
			</form>
		</aside>
	{/if}
</div>
