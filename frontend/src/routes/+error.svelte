<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import AuthPage from '$lib/design/AuthPage.svelte';
	import Panel from '$lib/design/Panel.svelte';
	import { t } from '$lib/i18n';
	import Button from '$lib/design/Button.svelte';
</script>

<AuthPage>
	<Panel class="grid grid-cols-1 gap-3">
		<h1>{page.status === 404 ? $t('Not found') : $t('Unable to open Quirebase')}</h1>
		<p class="text-surface-600-400">
			{page.error?.message ?? $t('This workspace route does not exist.')}
		</p>
		<Button as="a" href={resolve('/')}>{$t('Return to Quirebase')}</Button>
	</Panel>
</AuthPage>
