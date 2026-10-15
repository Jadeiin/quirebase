<script lang="ts">
	import type { Snippet } from 'svelte';
	import Icon from '#lib/design/Icon.svelte';
	import Panel from '#lib/design/Panel.svelte';
	import Button from '#lib/design/Button.svelte';

	let {
		icon,
		title,
		description,
		busy,
		submitLabel,
		submitDisabled = false,
		onsubmit,
		children
	} = $props<{
		icon: string;
		title: string;
		description: string;
		busy: boolean;
		submitLabel: string;
		submitDisabled?: boolean;
		onsubmit: (event: SubmitEvent) => void;
		children: Snippet;
	}>();
</script>

<Panel as="form" class="grid h-full min-w-0 grid-cols-1 gap-4" {onsubmit}>
	<div class="flex items-start gap-3">
		<span
			class="grid size-10 shrink-0 grid-cols-1 place-items-center rounded-lg bg-primary-50-950 text-primary-800-200"
			><Icon name={icon} size={20} /></span
		>
		<div class="min-w-0">
			<h2 class="mb-1">{title}</h2>
			<p class="mb-0 text-sm text-surface-600-400">{description}</p>
		</div>
	</div>
	{@render children()}
	<div class="mt-1 border-t border-surface-300-700 pt-4">
		<Button variant="filled" disabled={busy || submitDisabled}>{submitLabel}</Button>
	</div>
</Panel>
