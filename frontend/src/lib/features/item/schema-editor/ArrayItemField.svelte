<script lang="ts">
	import type { ComponentProps } from '@sjsf/form';
	import ArrayItem from '@sjsf/form/fields/array/array-item-field.svelte';
	import { getArrayContext, setArrayContext } from '@sjsf/form/fields/array/context.svelte';
	import { getFieldVisibility } from './field-visibility.svelte.js';

	let { value = $bindable(), ...props }: ComponentProps['arrayItemField'] = $props();
	const array = getArrayContext();
	const visibility = getFieldVisibility();
	setArrayContext({
		...array,
		moveItemUp(index) {
			array.moveItemUp(index);
			visibility.reindex(array.config().path, (previous) =>
				previous === index ? index - 1 : previous === index - 1 ? index : previous
			);
		},
		moveItemDown(index) {
			array.moveItemDown(index);
			visibility.reindex(array.config().path, (previous) =>
				previous === index ? index + 1 : previous === index + 1 ? index : previous
			);
		},
		removeItem(index) {
			array.removeItem(index);
			visibility.reindex(array.config().path, (previous) =>
				previous === index ? null : previous > index ? previous - 1 : previous
			);
		},
		copyItem(index) {
			array.copyItem(index);
			visibility.reindex(array.config().path, (previous) =>
				previous >= index ? previous + 1 : previous
			);
		}
	});
</script>

<ArrayItem {...props} bind:value />
