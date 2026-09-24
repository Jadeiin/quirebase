<script lang="ts">
	import ProjectWorkspace from '$lib/features/projects/ProjectWorkspace.svelte';
	import type { PageProps } from './$types';

	let { params }: PageProps = $props();
</script>

<ProjectWorkspace projectId={params.projectId} />
