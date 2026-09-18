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
		confirmLabel,
		busy = false,
		onConfirm
	} = $props<{
		open: boolean;
		title: string;
		body: string;
		confirmLabel: string;
		busy?: boolean;
		onConfirm: () => void;
	}>();
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
				<div class="mt-5 flex flex-wrap justify-end gap-2">
					<Dialog.CloseTrigger class={buttonClass('tonal')} disabled={busy}
						>{$t('Cancel')}</Dialog.CloseTrigger
					>
					<Button variant="danger-filled" disabled={busy} onclick={onConfirm}>{confirmLabel}</Button
					>
				</div>
			</Dialog.Content>
		</Dialog.Positioner>
	</Portal>
</Dialog>
