<script lang="ts">
	import { apiRequest } from '$lib/api/client';
	import { t } from '$lib/i18n';

	let username = $state('');
	let password = $state('');
	let error = $state('');
	let busy = $state(false);

	async function submit() {
		busy = true;
		error = '';
		try {
			await apiRequest('POST', '/session', {
				body: { username, password }
			});
			window.location.assign('/');
		} catch (reason) {
			error = reason instanceof Error ? reason.message : $t('Unable to sign in');
		} finally {
			busy = false;
		}
	}
</script>

<main class="workspace" style="max-width: 28rem; margin: 10vh auto;">
	<form
		class="stack card border border-surface-300 bg-surface-50 p-5 shadow-sm"
		onsubmit={(event) => {
			event.preventDefault();
			submit();
		}}
	>
		<h1 style="margin: 0;">Quirebase</h1>
		<p class="text-surface-600">{$t('Sign in to your research workspace.')}</p>
		<label
			>{$t('Username')}
			<input class="input" bind:value={username} autocomplete="username" required /></label
		>
		<label
			>{$t('Password')}
			<input
				class="input"
				bind:value={password}
				type="password"
				autocomplete="current-password"
				required
			/></label
		>
		{#if error}<p class="text-error-700" role="alert">{error}</p>{/if}
		<button class="btn preset-filled-primary-700-300 font-semibold" type="submit" disabled={busy}
			>{busy ? $t('Signing in…') : $t('Sign in')}</button
		>
	</form>
</main>
