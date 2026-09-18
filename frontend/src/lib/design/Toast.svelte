<script lang="ts">
	import { Toast } from '@skeletonlabs/skeleton-svelte';
	import Icon from '$lib/design/Icon.svelte';
	import { toaster } from '$lib/toaster';
	import { t } from '$lib/i18n';
</script>

<Toast.Group {toaster} class="group">
	{#snippet children(toast)}
		{@const progressDuration =
			typeof toast.duration === 'number' && Number.isFinite(toast.duration) ? toast.duration : null}
		<Toast
			{toast}
			class={[
				'relative flex w-full max-w-md items-center gap-2.5 overflow-hidden rounded-xl border px-4 py-3 shadow-lg',
				toast.type === 'success' && 'border-success-200-800 bg-surface-50-950 text-success-900-100',
				toast.type === 'error' && 'border-error-200-800 bg-surface-50-950 text-error-700-300',
				(toast.type === 'info' || toast.type === 'loading') &&
					'border-surface-300-700 bg-surface-50-950'
			]
				.filter(Boolean)
				.join(' ')}
		>
			{#if progressDuration !== null}
				<span
					class="toast-progress"
					style={`--toast-duration:${progressDuration}ms`}
					aria-hidden="true"
				></span>
			{/if}
			<Toast.Message class="relative z-1 min-w-0 flex-1">
				<Toast.Title class="text-sm font-medium">{toast.title}</Toast.Title>
			</Toast.Message>
			<Toast.CloseTrigger
				class="relative z-1 btn-icon shrink-0 preset-tonal-surface"
				aria-label={$t('Dismiss')}><Icon name="close" size={14} /></Toast.CloseTrigger
			>
		</Toast>
	{/snippet}
</Toast.Group>

<style>
	.toast-progress {
		position: absolute;
		inset: 0;
		border-radius: inherit;
		pointer-events: none;
		transform-origin: left center;
		background: linear-gradient(
			90deg,
			color-mix(in oklab, currentColor 16%, transparent),
			color-mix(in oklab, currentColor 5%, transparent) 65%,
			transparent
		);
		animation: toast-progress var(--toast-duration) linear forwards;
	}
	:global(.group):hover .toast-progress,
	:global(.group):focus-within .toast-progress {
		animation-play-state: paused;
	}
	@keyframes toast-progress {
		from {
			transform: scaleX(1);
		}
		to {
			transform: scaleX(0);
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.toast-progress {
			display: none;
		}
	}
</style>
