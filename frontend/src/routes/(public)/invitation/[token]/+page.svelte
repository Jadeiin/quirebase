<script lang="ts">
	import Invitation from '$lib/features/auth/Invitation.svelte';
	import type { PageProps } from './$types';

	let { params }: PageProps = $props();
</script>

<Invitation token={params.token} />
