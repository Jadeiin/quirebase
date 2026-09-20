<script lang="ts">
	import Notice from '$lib/design/Notice.svelte';

	let { error = '', notice = '' } = $props<{ error?: string; notice?: string }>();
</script>

{#if error}<Notice variant="error" class="mt-4">{error}</Notice>{/if}
{#if notice}<Notice variant="success" class="mt-4">{notice}</Notice>{/if}
