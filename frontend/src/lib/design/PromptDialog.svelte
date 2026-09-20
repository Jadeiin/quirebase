<script lang="ts">
	import { Dialog, Portal } from '@skeletonlabs/skeleton-svelte';
	import Button from '$lib/design/Button.svelte';
	import { buttonClass } from '$lib/design/button-classes';
	import DialogCloseButton from '$lib/design/DialogCloseButton.svelte';
	import SectionHeader from '$lib/design/SectionHeader.svelte';
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
		<Dialog.Positioner class="fixed inset-0 z-71 grid grid-cols-1 place-items-center p-4">
			<Dialog.Content
				class="w-full max-w-md rounded-container border border-surface-300-700 bg-surface-50-950 p-5 shadow-2xl"
			>
				<SectionHeader>
					<Dialog.Title class="text-lg font-bold">{title}</Dialog.Title>
					{#snippet actions()}
						<DialogCloseButton />
					{/snippet}
				</SectionHeader>
				<p class="mt-3 text-sm text-surface-600-400">{body}</p>
				<form
					class="mt-4 grid grid-cols-1 gap-3"
					onsubmit={(event) => {
						event.preventDefault();
						if (canConfirm) onConfirm(value);
					}}
				>
					<label class="grid grid-cols-1 gap-1"
						>{label}<input
							class="input"
							bind:value
							{placeholder}
							required={!requireMatch}
							autocomplete="off"
						/></label
					>
					<div class="flex flex-wrap justify-end gap-2">
						<Dialog.CloseTrigger class={buttonClass('tonal')} disabled={busy}
							>{$t('Cancel')}</Dialog.CloseTrigger
						>
						<Button variant="filled" type="submit" disabled={!canConfirm}>{confirmLabel}</Button>
					</div>
				</form>
			</Dialog.Content>
		</Dialog.Positioner>
	</Portal>
</Dialog>
