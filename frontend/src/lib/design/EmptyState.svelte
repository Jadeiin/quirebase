<script lang="ts">
	import Icon from '$lib/design/Icon.svelte';

	let {
		icon = 'library',
		title,
		detail = ''
	} = $props<{
		icon?: string;
		title: string;
		detail?: string;
	}>();
</script>

<div class="grid min-h-56 grid-cols-1 place-items-center gap-2 p-8 text-center">
	<span
		class="grid size-12 grid-cols-1 place-items-center rounded-full bg-surface-200-800 text-surface-600-400"
		><Icon name={icon} size={22} /></span
	><strong>{title}</strong>
	{#if detail}<span class="text-sm text-surface-600-400">{detail}</span>{/if}
</div>
