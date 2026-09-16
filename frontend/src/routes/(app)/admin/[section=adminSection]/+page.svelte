<script lang="ts">
	import Admin from '$lib/Admin.svelte';
	import type { PageProps } from './$types';

	let { params }: PageProps = $props();
</script>

<Admin section={params.section} />
