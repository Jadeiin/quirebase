<script lang="ts">
	import AppShell from '$lib/AppShell.svelte';

	let { children } = $props();
</script>

<AppShell>{@render children()}</AppShell>
