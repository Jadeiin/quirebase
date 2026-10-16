<script lang="ts">
	import Notice from '#lib/design/Notice.svelte';
	import { t, type MessageKey } from '#lib/i18n.js';

	let {
		error = '',
		notice = null
	}: {
		error?: string;
		notice?: MessageKey | null;
	} = $props();
</script>

{#if error}<Notice variant="error">{error}</Notice>{/if}
{#if notice}<Notice variant="success">{$t(notice)}</Notice>{/if}
