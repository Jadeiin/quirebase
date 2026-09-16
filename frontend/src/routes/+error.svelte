<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { t } from '$lib/i18n';
</script>

<main class="workspace auth-page">
	<section class="panel stack">
		<h1>{page.status === 404 ? $t('Not found') : $t('Unable to open Quirebase')}</h1>
		<p class="muted">{page.error?.message ?? $t('This workspace route does not exist.')}</p>
		<a class="button" href={resolve('/')}>{$t('Return to Quirebase')}</a>
	</section>
</main>
