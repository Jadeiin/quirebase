<script lang="ts">
	import { tick, type Snippet } from 'svelte';
	import { t } from '#lib/i18n.js';
	import { fitAuthorLine } from './author-line.js';

	let {
		names,
		author,
		onShowAll,
		expanded = false,
		controls
	}: {
		names: readonly string[];
		author?: Snippet<[number]>;
		onShowAll?: (trigger: HTMLElement) => void;
		expanded?: boolean;
		controls?: string;
	} = $props();

	let row = $state<HTMLSpanElement>();
	let measurements = $state<HTMLSpanElement>();
	let separator = $state<HTMLSpanElement>();
	let overflowMark = $state<HTMLSpanElement>();
	let layout = $state.raw({ prefixCount: 0, lastVisible: false, overflowing: true });

	$effect(() => {
		const currentNames = names;
		if (!row || !measurements || !separator || !overflowMark) return;
		const rowElement = row;
		const measurementElement = measurements;
		const separatorElement = separator;
		const overflowElement = overflowMark;
		let frame = 0;

		function measure() {
			const widths = Array.from(measurementElement.children)
				.slice(0, currentNames.length)
				.map((element) => element.getBoundingClientRect().width);
			const next = fitAuthorLine(
				widths,
				rowElement.getBoundingClientRect().width,
				separatorElement.getBoundingClientRect().width,
				overflowElement.getBoundingClientRect().width
			);
			if (
				next.prefixCount === layout.prefixCount &&
				next.lastVisible === layout.lastVisible &&
				next.overflowing === layout.overflowing
			)
				return;

			const focused = document.activeElement;
			const credit =
				focused instanceof HTMLElement ? focused.closest<HTMLElement>('[data-author-index]') : null;
			const index = credit ? Number(credit.dataset.authorIndex) : -1;
			const restoreFocus =
				focused instanceof HTMLElement &&
				rowElement.contains(focused) &&
				((credit &&
					index >= next.prefixCount &&
					!(next.lastVisible && index === currentNames.length - 1)) ||
					(!next.overflowing && overflowElement.contains(focused)));
			layout = next;
			if (restoreFocus) {
				void tick().then(() => {
					if (layout !== next || !rowElement.isConnected) return;
					if (document.activeElement !== focused && document.activeElement !== document.body)
						return;
					const target = next.overflowing
						? overflowElement.querySelector<HTMLButtonElement>('button')
						: rowElement
								.querySelector('[data-author-index]:not([hidden])')
								?.querySelector<HTMLElement>('a[href], button, [tabindex]');
					target?.focus();
				});
			}
		}
		function schedule() {
			cancelAnimationFrame(frame);
			frame = requestAnimationFrame(measure);
		}
		const observer = new ResizeObserver(schedule);
		observer.observe(rowElement);
		observer.observe(measurementElement);
		observer.observe(overflowElement);
		schedule();
		return () => {
			cancelAnimationFrame(frame);
			observer.disconnect();
		};
	});
</script>

<span
	class="relative flex max-w-full min-w-0 items-baseline overflow-hidden"
	title={names.join('; ')}
	bind:this={row}
>
	<span
		class="pointer-events-none invisible absolute top-0 left-0 flex w-max whitespace-nowrap"
		aria-hidden="true"
		inert
		bind:this={measurements}
	>
		{#each names as name, index (index)}<span>{name}</span>{/each}
		<span bind:this={separator}>;&nbsp;</span>
	</span>
	{#each names as name, index (index)}
		{@const last = index === names.length - 1}
		{#if last}
			<span
				class={layout.overflowing
					? 'inline-flex shrink-0 items-baseline whitespace-nowrap'
					: 'pointer-events-none invisible absolute inline-flex items-baseline whitespace-nowrap'}
				aria-hidden={!layout.overflowing}
				inert={!layout.overflowing}
			>
				{#if layout.overflowing && layout.prefixCount}<span aria-hidden="true">;&nbsp;</span>{/if}
				<span class="inline-flex shrink-0 items-baseline" bind:this={overflowMark}>
					{#if onShowAll && layout.overflowing}
						<button
							type="button"
							class="px-0.5 hover:text-primary-700-300"
							aria-label={$t('Show all authors')}
							title={$t('Show all authors')}
							aria-expanded={expanded}
							aria-controls={expanded ? controls : undefined}
							onclick={(event) => onShowAll?.(event.currentTarget)}>…</button
						>
					{:else}<span class={onShowAll ? 'px-0.5' : ''}>…</span>{/if}
				</span>
			</span>
		{/if}
		<span
			class="inline-flex shrink-0 items-baseline whitespace-nowrap"
			data-author-index={index}
			hidden={last ? !layout.lastVisible : index >= layout.prefixCount}
		>
			{#if last ? layout.prefixCount || layout.overflowing : index}
				<span aria-hidden="true">;&nbsp;</span>
			{/if}
			{#if author}{@render author(index)}{:else}<span dir="auto">{name}</span>{/if}
		</span>
	{/each}
</span>
