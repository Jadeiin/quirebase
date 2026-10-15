<script lang="ts">
	import { getFormContext, layoutAttributes, type ComponentProps } from '@sjsf/form';
	let { type, children, config }: ComponentProps['layout'] = $props();
	const ctx = getFormContext();
	const column = $derived(
		[
			'field',
			'multi-field',
			'array-field',
			'object-field',
			'array-items',
			'object-properties'
		].includes(type)
	);
	const row = $derived(
		type.endsWith('title-row') || type === 'array-item-controls' || type === 'multi-field-controls'
	);
	// Nested objects size their own columns instead of inheriting a viewport breakpoint.
	const presentation = $derived.by(() => {
		if (type === 'field') return 'grid w-full grid-cols-1 gap-2';
		if (type === 'object-field') return '@container/schema grid w-full grid-cols-1 gap-4';
		if (type === 'object-properties')
			return 'grid w-full grid-cols-1 items-start gap-4 @min-[24rem]/schema:grid-cols-2 @min-[48rem]/schema:grid-cols-3';
		if (type === 'object-property') {
			const wide =
				['object', 'array'].includes(String(config.schema.type)) ||
				['description', 'content'].includes(String(config.path.at(-1)));
			return wide ? 'col-span-full w-full' : 'w-full';
		}
		if (type === 'array-field')
			return '@container/schema-array grid w-full grid-cols-1 gap-4 [&>button]:justify-self-start';
		if (type === 'array-items')
			return 'grid w-full grid-cols-1 items-start gap-4 @min-[48rem]/schema-array:grid-cols-[repeat(auto-fit,minmax(22rem,1fr))]';
		if (type === 'array-item')
			return 'grid w-full grid-cols-1 gap-3 rounded-lg border border-surface-300-700 p-3';
		if (column) return 'grid w-full grid-cols-1 gap-4';
		if (row) return 'flex flex-wrap items-center gap-2';
		return 'w-full';
	});
</script>

{#if type === 'field-content'}
	{@render children()}
{:else}
	<div
		class={`min-w-0 ${presentation}`}
		{...layoutAttributes(ctx, config, 'layout', 'layouts', type, {})}
	>
		{@render children()}
	</div>
{/if}
