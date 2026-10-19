<script lang="ts">
	import WorkspaceSettings from '#lib/features/workspaces/WorkspaceSettings.svelte';
	let { children } = $props();
</script>

<WorkspaceSettings>{@render children()}</WorkspaceSettings>
