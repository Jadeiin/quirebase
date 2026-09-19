<script lang="ts">
	import { Popover } from '@skeletonlabs/skeleton-svelte';
	import Icon from '$lib/design/Icon.svelte';
	import { t } from '$lib/i18n';
</script>

<Popover.CloseTrigger class="btn-icon preset-tonal-surface" aria-label={$t('Close')}>
	<Icon name="close" size={14} />
</Popover.CloseTrigger>
