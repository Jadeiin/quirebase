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
	// Intrinsic tracks follow available width without size-containment invalidation
	// when a hidden field is revealed inside a collapsed details element.
	const presentation = $derived.by(() => {
		if (type === 'field') return 'grid w-full grid-cols-1 gap-2';
		if (type === 'object-field') return 'grid w-full grid-cols-1 gap-4';
		if (type === 'object-properties')
			return 'grid w-full grid-cols-[repeat(auto-fit,minmax(min(100%,max(11rem,calc((100%_-_2rem)/3))),1fr))] items-start gap-4';
		if (type === 'object-property') {
			const wide =
				['object', 'array'].includes(String(config.schema.type)) ||
				['description', 'content'].includes(String(config.path.at(-1)));
			return wide ? 'col-span-full w-full' : 'w-full';
		}
		if (type === 'array-field')
			return 'grid w-full grid-cols-1 gap-4 [&>button]:justify-self-start';
		if (type === 'array-items')
			return 'grid w-full grid-cols-[repeat(auto-fit,minmax(min(100%,22rem),1fr))] items-start gap-4';
		if (type === 'array-item')
			return config.path.length > 2
				? 'grid w-full grid-cols-1 gap-3 border-t border-surface-300-700 pt-3'
				: 'grid w-full grid-cols-1 gap-3 rounded-lg border border-surface-300-700 p-3';
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
