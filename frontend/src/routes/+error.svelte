<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { t } from '$lib/i18n';
</script>

<main class="workspace auth-page">
	<section class="stack card border border-surface-300-700 bg-surface-50-950 p-5 shadow-sm">
		<h1>{page.status === 404 ? $t('Not found') : $t('Unable to open Quirebase')}</h1>
		<p class="text-surface-600-400">
			{page.error?.message ?? $t('This workspace route does not exist.')}
		</p>
		<a class="btn preset-tonal-surface font-semibold" href={resolve('/')}
			>{$t('Return to Quirebase')}</a
		>
	</section>
</main>
