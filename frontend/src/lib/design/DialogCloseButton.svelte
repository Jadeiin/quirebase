<script lang="ts">
	import { Dialog } from '@skeletonlabs/skeleton-svelte';
	import Icon from '#lib/design/Icon.svelte';
	import { t } from '#lib/i18n.js';
</script>

<Dialog.CloseTrigger class="btn-icon preset-tonal-surface" aria-label={$t('Close')}>
	<Icon name="close" />
</Dialog.CloseTrigger>
