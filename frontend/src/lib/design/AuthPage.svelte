<script lang="ts">
	import type { Snippet } from 'svelte';

	let { children } = $props<{ children: Snippet }>();
</script>

<main class="mx-auto w-full max-w-md p-4 pt-[10vh] md:p-[clamp(1.25rem,3vw,2.75rem)] md:pt-[10vh]">
	{@render children()}
</main>
