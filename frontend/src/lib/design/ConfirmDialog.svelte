<script lang="ts">
	import { Dialog, Portal } from '@skeletonlabs/skeleton-svelte';
	import Icon from '$lib/design/Icon.svelte';
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
				<div class="toolbar mt-5 justify-end">
					<Dialog.CloseTrigger class="btn preset-tonal-surface font-semibold" disabled={busy}
						>{$t('Cancel')}</Dialog.CloseTrigger
					>
					<button
						class="btn preset-filled-error-700-300 font-semibold"
						disabled={busy}
						onclick={onConfirm}>{confirmLabel}</button
					>
				</div>
			</Dialog.Content>
		</Dialog.Positioner>
	</Portal>
</Dialog>
