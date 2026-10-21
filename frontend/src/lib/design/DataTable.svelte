<script lang="ts">
	import type { Snippet } from 'svelte';

	let { label, children }: { label: string; children: Snippet } = $props();
</script>

<div data-table class="min-w-0">
	<table class="table w-full table-fixed text-sm">
		<caption class="sr-only">{label}</caption>
		{@render children()}
	</table>
</div>

<style>
	[data-table] :global(th),
	[data-table] :global(td) {
		padding: 0.875rem 1rem;
		text-align: start;
		vertical-align: top;
		overflow-wrap: anywhere;
	}
	[data-table] :global(thead th) {
		background: var(--color-surface-100-900);
		font-weight: 600;
	}
	[data-table] :global(tbody + tbody) {
		border-top: 1px solid var(--color-surface-300-700);
	}
	[data-table] :global(tr[hidden]) {
		display: none;
	}
	@media (width < 64rem) {
		[data-table] :global(table),
		[data-table] :global(tbody),
		[data-table] :global(tr:not([hidden])) {
			display: block;
		}
		[data-table] :global(thead) {
			position: absolute;
			width: 1px;
			height: 1px;
			padding: 0;
			margin: -1px;
			overflow: hidden;
			clip-path: inset(50%);
			white-space: nowrap;
		}
		[data-table] :global(tbody) {
			padding-block: 0.5rem;
		}
		[data-table] :global(tbody th),
		[data-table] :global(td) {
			display: block;
			padding-block: 0.375rem;
		}
		[data-table] :global(td[data-label]) {
			display: grid;
			grid-template-columns: minmax(5rem, 1fr) minmax(0, 3fr);
			gap: 0.75rem;
		}
		[data-table] :global(td[data-label]::before) {
			content: attr(data-label);
			font-weight: 500;
			color: var(--color-surface-600-400);
		}
	}
</style>
