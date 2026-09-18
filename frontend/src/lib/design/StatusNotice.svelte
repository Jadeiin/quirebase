<script lang="ts">
	let { error = '', notice = '' } = $props<{ error?: string; notice?: string }>();
</script>

{#if error}<p class="mt-4 text-error-700-300" role="alert">{error}</p>{/if}
{#if notice}<p
		class="mt-4 rounded-base border border-success-200-800 preset-tonal-success px-4 py-3 text-success-900-100"
		role="status"
	>
		{notice}
	</p>{/if}
