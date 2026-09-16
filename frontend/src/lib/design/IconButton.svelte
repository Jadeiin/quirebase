<script lang="ts">
	import { Tooltip } from 'bits-ui';
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

<Tooltip.Root>
	<Tooltip.Trigger
		type="button"
		class={`inline-grid size-9 shrink-0 cursor-pointer place-items-center rounded-md border transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${active ? 'border-line bg-accent-soft text-accent-strong' : 'border-transparent bg-transparent text-current hover:border-line hover:bg-muted-surface hover:text-accent-strong'}`}
		aria-label={label}
		aria-pressed={active || undefined}
		{disabled}
		{onclick}
	>
		<Icon name={icon} />
	</Tooltip.Trigger>
	<Tooltip.Portal>
		<Tooltip.Content
			class="z-100 rounded-md bg-[#17251f] px-2 py-1 text-xs text-white shadow-xl"
			sideOffset={7}>{label}</Tooltip.Content
		>
	</Tooltip.Portal>
</Tooltip.Root>
