<script lang="ts">
	import type { Snippet } from 'svelte';

	let { label, children } = $props<{ label: string; children: Snippet }>();
</script>

<nav class="mb-4 flex gap-1 overflow-x-auto border-b border-surface-300-700" aria-label={label}>
	{@render children()}
</nav>
