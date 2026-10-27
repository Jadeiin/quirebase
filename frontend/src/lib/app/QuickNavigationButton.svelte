<script lang="ts">
	import { detectPlatform, formatForDisplay } from '@tanstack/svelte-hotkeys';
	import Icon from '#lib/design/Icon.svelte';
	import { t } from 'lingui-for-svelte/macro';

	let { compact = false, onOpen }: { compact?: boolean; onOpen: () => void } = $props();
	const shortcut = formatForDisplay('Mod+K');
</script>

<button
	type="button"
	class={`cursor-pointer rounded-lg border-0 bg-white/7 text-white hover:bg-white/12 ${compact ? 'mx-auto grid size-8 shrink-0 grid-cols-1 place-items-center' : 'flex w-full items-center gap-2.5 px-3 py-2.5 text-left text-sm'}`}
	aria-label={compact ? $t`Quick navigation` : undefined}
	aria-keyshortcuts={detectPlatform() === 'mac' ? 'Meta+K' : 'Control+K'}
	title={`${$t`Quick navigation`} (${shortcut})`}
	onclick={onOpen}
>
	<Icon name="search" size={18} />
	{#if !compact}
		<span class="min-w-0 flex-1">{$t`Quick navigation`}</span>
		<kbd class="shrink-0 text-xs text-surface-400" aria-hidden="true">{shortcut}</kbd>
	{/if}
</button>
