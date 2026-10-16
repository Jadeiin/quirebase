<script lang="ts">
	import type { Snippet } from 'svelte';
	import { provideWorkspaceContext } from '#lib/workspaces/context.svelte.js';
	import type { WorkspaceView } from '#lib/api/client.js';

	let {
		workspaceId,
		view,
		children
	}: {
		workspaceId: string;
		view?: WorkspaceView;
		children: Snippet;
	} = $props();
	// The parent keys this provider by workspaceId, so the ID is fixed for this instance.
	// svelte-ignore state_referenced_locally
	provideWorkspaceContext(workspaceId, () => view);
</script>

{@render children()}
