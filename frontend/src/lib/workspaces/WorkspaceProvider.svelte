<script lang="ts">
	import type { Snippet } from 'svelte';
	import { provideWorkspaceContext } from '$lib/workspaces/context.svelte';
	import type { WorkspaceView } from '$lib/api/client';

	let { workspaceId, view, children } = $props<{
		workspaceId: string;
		view?: WorkspaceView;
		children: Snippet;
	}>();
	// The parent keys this provider by workspaceId, so the ID is fixed for this instance.
	// svelte-ignore state_referenced_locally
	provideWorkspaceContext(workspaceId, () => view);
</script>

{@render children()}
