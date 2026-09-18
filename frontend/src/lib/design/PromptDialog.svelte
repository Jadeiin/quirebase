<script lang="ts">
	import { Dialog, Portal } from '@skeletonlabs/skeleton-svelte';
	import Icon from '$lib/design/Icon.svelte';
	import { t } from '$lib/i18n';

	let {
		open = $bindable(false),
		title,
		body,
		label,
		placeholder = '',
		initialValue = '',
		confirmLabel,
		requireMatch = '',
		busy = false,
		onConfirm
	} = $props<{
		open: boolean;
		title: string;
		body: string;
		label: string;
		placeholder?: string;
		initialValue?: string;
		confirmLabel: string;
		requireMatch?: string;
		busy?: boolean;
		onConfirm: (value: string) => void;
	}>();

	let value = $state('');
	$effect(() => {
		if (open) value = initialValue;
	});
	const canConfirm = $derived(!busy && (requireMatch ? value === requireMatch : true));
</script>

<Dialog {open} onOpenChange={(details) => (open = details.open)}>
	<Portal>
		<Dialog.Backdrop class="fixed inset-0 z-70 bg-surface-950/45 backdrop-blur-[2px]" />
		<Dialog.Positioner class="fixed inset-0 z-71 grid place-items-center p-4">
			<Dialog.Content
				class="w-full max-w-md rounded-container border border-surface-300-700 bg-surface-50-950 p-5 shadow-2xl"
			>
				<div class="workspace-header">
					<div><Dialog.Title class="text-lg font-bold">{title}</Dialog.Title></div>
					<Dialog.CloseTrigger class="btn-icon preset-tonal-surface" aria-label={$t('Close')}
						><Icon name="close" /></Dialog.CloseTrigger
					>
				</div>
				<p class="mt-3 text-sm text-surface-600-400">{body}</p>
				<form
					class="stack mt-4"
					onsubmit={(event) => {
						event.preventDefault();
						if (canConfirm) onConfirm(value);
					}}
				>
					<label class="stack gap-1"
						>{label}<input
							class="input"
							bind:value
							{placeholder}
							required={!requireMatch}
							autocomplete="off"
						/></label
					>
					<div class="toolbar justify-end">
						<Dialog.CloseTrigger class="btn preset-tonal-surface font-semibold" disabled={busy}
							>{$t('Cancel')}</Dialog.CloseTrigger
						>
						<button
							type="submit"
							class="btn preset-filled-primary-700-300 font-semibold"
							disabled={!canConfirm}>{confirmLabel}</button
						>
					</div>
				</form>
			</Dialog.Content>
		</Dialog.Positioner>
	</Portal>
</Dialog>
