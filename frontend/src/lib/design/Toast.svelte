<script lang="ts">
	import { Toast } from '@skeletonlabs/skeleton-svelte';
	import Icon from '$lib/design/Icon.svelte';
	import { toaster } from '$lib/toaster';
	import { t } from '$lib/i18n';
</script>

<Toast.Group {toaster}>
	{#snippet children(toast)}
		<Toast
			{toast}
			class={[
				'flex w-full max-w-md items-center gap-2.5 rounded-xl border px-4 py-3 shadow-lg',
				toast.type === 'success' && 'border-success-200-800 bg-surface-50-950 text-success-900-100',
				toast.type === 'error' && 'border-error-200-800 bg-surface-50-950 text-error-700-300',
				(toast.type === 'info' || toast.type === 'loading') &&
					'border-surface-300-700 bg-surface-50-950'
			]
				.filter(Boolean)
				.join(' ')}
		>
			<Toast.Message class="min-w-0 flex-1">
				<Toast.Title class="text-sm font-medium">{toast.title}</Toast.Title>
			</Toast.Message>
			<Toast.CloseTrigger class="btn-icon shrink-0 preset-tonal-surface" aria-label={$t('Dismiss')}
				><Icon name="close" size={14} /></Toast.CloseTrigger
			>
		</Toast>
	{/snippet}
</Toast.Group>
