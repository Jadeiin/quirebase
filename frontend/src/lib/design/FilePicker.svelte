<script lang="ts">
	import { FileUpload, useFileUpload } from '@skeletonlabs/skeleton-svelte';
	import Badge from '#lib/design/Badge.svelte';
	import Icon from '#lib/design/Icon.svelte';
	import IconButton from '#lib/design/IconButton.svelte';
	import Notice from '#lib/design/Notice.svelte';
	import { kilobytes, numberFormat } from '#lib/format.js';
	import { t } from '#lib/i18n.js';

	type FilePickerProps = {
		name: string;
		label: string;
		hint?: string;
		actionLabel: string;
		accept?: string[];
		multiple?: boolean;
		maxFiles?: number;
		disabled?: boolean;
		required?: boolean;
		onFilesChange?: (files: File[]) => void;
		class?: string;
	};

	let {
		name,
		label,
		hint = '',
		actionLabel,
		accept = [],
		multiple = false,
		maxFiles = 50,
		disabled = false,
		required = false,
		onFilesChange,
		class: className = ''
	}: FilePickerProps = $props();

	const id = $props.id();
	const fileUpload = useFileUpload(() => ({
		id,
		name,
		accept,
		disabled,
		required,
		maxFiles: multiple ? maxFiles : 1,
		translations: { dropzone: `${label} ${actionLabel}` },
		onFileChange: (details) => {
			onFilesChange?.(details.acceptedFiles);
			// A rejected selection leaves the rejected file in the native input
			// while the machine keeps the accepted files; re-assert the accepted
			// state so `new FormData(form)` can never submit a rejected file.
			restoreHiddenInput();
		}
	}));
	const api = $derived(fileUpload());
	let hiddenInput = $state<HTMLInputElement | null>(null);
	let clearWhenEnabled = $state(false);

	export function clearFiles() {
		// Clearing may be requested while the picker is disabled (for example when
		// a mutation settles first); defer it until the machine accepts commands.
		if (api.disabled) {
			clearWhenEnabled = true;
			return;
		}
		api.clearFiles();
	}

	// Zag clears the hidden input before opening the picker so that re-selecting
	// the same file still fires `input`, and leaves rejected selections in the
	// native input while the machine keeps the accepted files. Re-assert the
	// accepted state (clearing the input when nothing is accepted) so a submitted
	// FormData always matches the displayed files.
	function restoreHiddenInput() {
		if (!hiddenInput) return;
		try {
			const transfer = new DataTransfer();
			for (const file of api.acceptedFiles) transfer.items.add(file);
			hiddenInput.files = transfer.files;
		} catch {
			// Browsers without DataTransfer cannot repair the input; the machine
			// state remains authoritative for rendering.
		}
	}

	$effect(() => {
		if (!clearWhenEnabled || api.disabled) return;
		clearWhenEnabled = false;
		api.clearFiles();
	});
</script>

<FileUpload.Provider
	value={fileUpload}
	class={`grid min-w-0 grid-cols-1 gap-3 ${className}`.trim()}
>
	<FileUpload.Dropzone
		aria-describedby={hint ? `${id}-hint` : undefined}
		class="flex min-w-0 cursor-pointer flex-row items-center justify-between gap-3 rounded-base border border-dashed border-surface-400-600 bg-surface-50-950 px-4 py-3 transition-colors hover:border-primary-700-300 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-700 data-disabled:cursor-not-allowed data-disabled:opacity-60 data-dragging:border-primary-700-300 data-dragging:bg-primary-50-950"
	>
		<span class="min-w-0">
			<strong class="block text-sm">{label}</strong>
		</span>
		<span
			class="shrink-0 rounded-full border border-surface-300-700 px-3 py-1 text-sm font-semibold text-primary-700-300"
			>{actionLabel}</span
		>
	</FileUpload.Dropzone>
	{#if hint}<small id={`${id}-hint`} class="block text-surface-600-400">{hint}</small>{/if}
	<FileUpload.HiddenInput>
		{#snippet element(attributes)}
			<input
				{...attributes}
				bind:this={hiddenInput}
				oninput={(event) => {
					attributes.oninput?.(event);
					// Repeating the same rejection leaves machine state unchanged,
					// so onFileChange does not run for every native selection.
					restoreHiddenInput();
				}}
				onclick={(event) => {
					attributes.onclick?.(event);
					restoreHiddenInput();
				}}
			/>
		{/snippet}
	</FileUpload.HiddenInput>
	{#if api.acceptedFiles.length}
		<ul class="m-0 grid min-w-0 list-none grid-cols-1 gap-2 p-0" aria-live="polite">
			{#each api.acceptedFiles as file (file)}
				<li
					class="flex min-w-0 items-center justify-between gap-3 rounded-base border border-surface-300-700 px-4 py-2.5"
				>
					<span class="flex min-w-0 items-center gap-2">
						<Icon name="file" size={16} />
						<span class="min-w-0 truncate text-sm" title={file.name}>{file.name}</span>
					</span>
					<span class="flex shrink-0 items-center gap-1">
						<span class="text-sm text-surface-600-400"
							>{$t('{size} KB', { size: $numberFormat.format(kilobytes(file.size)) })}</span
						>
						<IconButton
							label={$t('Remove {name}', { name: file.name })}
							icon="close"
							onclick={() => {
								api.deleteFile(file);
								api.clearRejectedFiles();
							}}
						/>
					</span>
				</li>
			{/each}
		</ul>
	{/if}
	{#if api.rejectedFiles.length}
		<Notice variant="warning" class="flex flex-wrap items-center gap-x-2 gap-y-1">
			<Badge variant="warning">{api.rejectedFiles.length}</Badge>
			<span
				>{$t(
					'Some files were skipped because they are duplicates, unsupported, or over the batch limit.'
				)}</span
			>
		</Notice>
	{/if}
</FileUpload.Provider>
