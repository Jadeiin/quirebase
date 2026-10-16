<script lang="ts">
	import { Progress } from '@skeletonlabs/skeleton-svelte';
	let { label, class: className = '' }: { label: string; class?: string } = $props();
</script>

<Progress value={null} class={`max-w-sm text-sm text-surface-600-400 ${className}`.trim()}>
	<Progress.Label>{label}</Progress.Label>
	<Progress.Track class="h-1"
		><Progress.Range class="bg-primary-700-300 motion-reduce:animate-none" /></Progress.Track
	>
</Progress>
