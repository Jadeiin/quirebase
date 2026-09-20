<script lang="ts">
	import AppShell from '$lib/app/AppShell.svelte';

	let { children } = $props();
</script>

<AppShell>{@render children()}</AppShell>
