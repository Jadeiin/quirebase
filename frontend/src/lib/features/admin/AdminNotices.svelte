<script lang="ts">
	import Notice from '#lib/design/Notice.svelte';
	import { t } from 'lingui-for-svelte/macro';
	import type { MessageDescriptor } from '@lingui/core';

	let {
		error = '',
		notice = null
	}: {
		error?: string;
		notice?: MessageDescriptor | null;
	} = $props();
</script>

{#if error}<Notice variant="error">{error}</Notice>{/if}
{#if notice}<Notice variant="success">{$t(notice)}</Notice>{/if}
