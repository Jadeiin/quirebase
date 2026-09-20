<script lang="ts">
	import { Portal, Tooltip } from '@skeletonlabs/skeleton-svelte';
	import Icon from '$lib/design/Icon.svelte';

	let {
		label,
		icon,
		active = false,
		disabled = false,
		onclick
	} = $props<{
		label: string;
		icon: string;
		active?: boolean;
		disabled?: boolean;
		onclick?: (event: MouseEvent) => void;
	}>();
</script>

<Tooltip openDelay={450} closeDelay={100} positioning={{ placement: 'bottom', gutter: 7 }}>
	<Tooltip.Trigger
		type="button"
		class={`inline-grid size-9 shrink-0 cursor-pointer place-items-center rounded-md border transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${active ? 'border-surface-300-700 bg-primary-50-950 text-primary-800-200' : 'border-transparent bg-transparent text-current hover:border-surface-300-700 hover:bg-surface-200-800 hover:text-primary-800-200'}`}
		aria-label={label}
		aria-pressed={active || undefined}
		{disabled}
		{onclick}
	>
		<Icon name={icon} />
	</Tooltip.Trigger>
	<Portal>
		<Tooltip.Positioner class="z-100">
			<Tooltip.Content class="rounded-base bg-surface-900 px-2 py-1 text-xs text-white shadow-xl"
				>{label}</Tooltip.Content
			>
		</Tooltip.Positioner>
	</Portal>
</Tooltip>
