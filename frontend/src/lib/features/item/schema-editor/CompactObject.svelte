<script lang="ts">
	import type { ComponentProps } from '@sjsf/form';
	import ObjectTemplate from '@sjsf/form/templates/object.svelte';
	import AddField from './AddField.svelte';

	let { children, ...props }: ComponentProps['objectTemplate'] = $props();
</script>

<ObjectTemplate {...props}>
	{@render children()}
	<AddField config={props.config} value={props.value} />
</ObjectTemplate>
