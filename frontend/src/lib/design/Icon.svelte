<script lang="ts">
	let { name, size = 18 } = $props<{ name: string; size?: number }>();
</script>

<svg
	class="block shrink-0"
	width={size}
	height={size}
	viewBox="0 0 24 24"
	fill="none"
	stroke="currentColor"
	stroke-width="1.8"
	stroke-linecap="round"
	stroke-linejoin="round"
	aria-hidden="true"
>
	{#if name === 'dashboard'}
		<rect x="3" y="3" width="7" height="7" rx="1" /><rect
			x="14"
			y="3"
			width="7"
			height="7"
			rx="1"
		/><rect x="3" y="14" width="7" height="7" rx="1" /><rect
			x="14"
			y="14"
			width="7"
			height="7"
			rx="1"
		/>
	{:else if name === 'library'}
		<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" /><path
			d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2Z"
		/>
	{:else if name === 'import'}
		<path d="M12 3v12" /><path d="m7 10 5 5 5-5" /><path d="M5 21h14" />
	{:else if name === 'search'}
		<circle cx="11" cy="11" r="7" /><path d="m20 20-4-4" />
	{:else if name === 'projects'}
		<path d="M3 7h7l2 2h9v10H3Z" /><path d="M3 7V5h7l2 2" />
	{:else if name === 'settings'}
		<path d="M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Z" /><path
			d="m19.4 15 .1.1 1.3 1-1.4 2.4-1.6-.6a7.8 7.8 0 0 1-1.5.9l-.3 1.7h-2.8l-.3-1.7a7.8 7.8 0 0 1-1.5-.9l-1.6.6-1.4-2.4 1.3-1a7 7 0 0 1 0-1.8l-1.3-1 1.4-2.4 1.6.6a7.8 7.8 0 0 1 1.5-.9l.3-1.7H16l.3 1.7a7.8 7.8 0 0 1 1.5.9l1.6-.6 1.4 2.4-1.3 1a7 7 0 0 1-.1 1.7Z"
		/>
	{:else if name === 'tools'}
		<path d="m14.7 6.3 3-3a4 4 0 0 1-5 5l-7.5 7.5a2.1 2.1 0 0 0 3 3l7.5-7.5a4 4 0 0 0 5-5l-3 3" />
	{:else if name === 'admin'}
		<path d="M12 3 4 7v5c0 5 3.4 8 8 9 4.6-1 8-4 8-9V7Z" /><path d="m9 12 2 2 4-4" />
	{:else if name === 'more'}
		<circle cx="5" cy="12" r="1" fill="currentColor" stroke="none" /><circle
			cx="12"
			cy="12"
			r="1"
			fill="currentColor"
			stroke="none"
		/><circle cx="19" cy="12" r="1" fill="currentColor" stroke="none" />
	{:else if name === 'user'}
		<circle cx="12" cy="8" r="4" /><path d="M4 21a8 8 0 0 1 16 0" />
	{:else if name === 'panel'}
		<rect x="3" y="4" width="18" height="16" rx="2" /><path d="M9 4v16" />
	{:else if name === 'hand'}
		<path
			d="M8 11V6a2 2 0 0 1 4 0v4-6a2 2 0 0 1 4 0v6-4a2 2 0 0 1 4 0v7a8 8 0 0 1-8 8h-1a7 7 0 0 1-6-3l-3-4a2 2 0 0 1 3-3l3 3"
		/>
	{:else if name === 'minus'}
		<path d="M5 12h14" />
	{:else if name === 'plus'}
		<path d="M12 5v14M5 12h14" />
	{:else if name === 'rotate'}
		<path d="M20 7v5h-5" /><path d="M19 12a7 7 0 1 1-2-5" />
	{:else if name === 'undo'}
		<path d="m9 7-5 5 5 5" /><path d="M20 17a8 8 0 0 0-8-8H4" />
	{:else if name === 'redo'}
		<path d="m15 7 5 5-5 5" /><path d="M4 17a8 8 0 0 1 8-8h8" />
	{:else if name === 'download'}
		<path d="M12 3v12m-5-5 5 5 5-5M5 21h14" />
	{:else if name === 'chevron-left'}
		<path d="m15 18-6-6 6-6" />
	{:else if name === 'chevron-right'}
		<path d="m9 18 6-6-6-6" />
	{:else if name === 'chevrons-left'}
		<path d="m13 18-6-6 6-6" /><path d="m19 18-6-6 6-6" />
	{:else if name === 'chevrons-right'}
		<path d="m11 18 6-6-6-6" /><path d="m5 18 6-6-6-6" />
	{:else if name === 'chevron-down'}
		<path d="m6 9 6 6 6-6" />
	{:else if name === 'close'}
		<path d="M6 6l12 12M18 6 6 18" />
	{:else if name === 'annotation'}
		<path d="M4 4h16v13H8l-4 4Z" /><path d="M8 8h8M8 12h5" />
	{:else if name === 'monitor'}
		<rect x="3" y="4" width="18" height="13" rx="2" /><path d="M8 21h8M12 17v4" />
	{:else if name === 'sun'}
		<circle cx="12" cy="12" r="4" /><path
			d="M12 2v2M12 20v2M4.93 4.93l1.42 1.42M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.42-1.42M17.66 6.34l1.41-1.41"
		/>
	{:else if name === 'moon'}
		<path d="M20.5 14.2A8 8 0 0 1 9.8 3.5 8.5 8.5 0 1 0 20.5 14.2Z" />
	{/if}
</svg>
