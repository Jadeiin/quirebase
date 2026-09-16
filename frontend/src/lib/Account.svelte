<script lang="ts">
	import { onMount } from 'svelte';
	import { createQuery } from '@tanstack/svelte-query';
	import { apiRequest } from '$lib/api/client';
	import { domainLabel } from '$lib/domain-labels';
	import ExportPreferences from '$lib/ExportPreferences.svelte';
	import { activateLocale, msg, t, type MessageKey } from '$lib/i18n';

	type AccountView = {
		user: { id: string; username: string; role: string };
		sessions: Array<{ id: string; current: boolean; created_at: string; expires_at: string }>;
		api_tokens: Array<{
			id: string;
			name: string;
			status: string;
			expires_at: string;
		}>;
	};

	let tokenName = $state('');
	let tokenDays = $state(30);
	let createdToken = $state('');
	let selectedLocale = $state('en-US');
	let externalOrigin = $state('');
	let sidebarCollapsed = $state(false);
	let error = $state('');
	let notice = $state<MessageKey | null>(null);
	let busy = $state(false);
	const account = createQuery(() => ({
		queryKey: ['account'],
		queryFn: () => apiRequest<AccountView>('/account')
	}));

	onMount(() => {
		selectedLocale = document.documentElement.lang === 'zh-CN' ? 'zh-CN' : 'en-US';
		externalOrigin = location.origin;
		sidebarCollapsed = localStorage.getItem('quirebase:sidebar-collapsed') === 'true';
	});

	function saveSidebarPreference() {
		localStorage.setItem('quirebase:sidebar-collapsed', String(sidebarCollapsed));
	}

	async function mutate(
		operation: () => Promise<unknown>,
		success: MessageKey,
		form?: HTMLFormElement
	) {
		busy = true;
		error = '';
		notice = null;
		try {
			await operation();
			await account.refetch();
			form?.reset();
			notice = success;
		} catch (reason) {
			error = reason instanceof Error ? reason.message : $t('Account action failed');
		} finally {
			busy = false;
		}
	}

	async function navigateAfter(operation: () => Promise<unknown>) {
		if (busy) return;
		busy = true;
		error = '';
		notice = null;
		try {
			await operation();
			location.assign('/');
		} catch (reason) {
			error = reason instanceof Error ? reason.message : $t('Account action failed');
		} finally {
			busy = false;
		}
	}

	async function createToken() {
		busy = true;
		error = '';
		notice = null;
		try {
			const grant = await apiRequest<{ token: string }>('/account/api-tokens', {
				method: 'POST',
				body: { name: tokenName, days: tokenDays }
			});
			createdToken = grant.token;
			tokenName = '';
			await account.refetch();
		} catch (reason) {
			error = reason instanceof Error ? reason.message : $t('Unable to create token');
		} finally {
			busy = false;
		}
	}

	function changePassword(event: SubmitEvent) {
		event.preventDefault();
		const form = event.currentTarget as HTMLFormElement;
		const values = new FormData(form);
		void mutate(
			() =>
				apiRequest('/account/password', {
					method: 'PUT',
					body: {
						current_password: values.get('current_password'),
						new_password: values.get('new_password')
					}
				}),
			msg('Password changed'),
			form
		);
	}

	async function saveLocale(event: SubmitEvent) {
		event.preventDefault();
		busy = true;
		error = '';
		notice = null;
		try {
			await apiRequest('/account/locale', {
				method: 'PUT',
				body: { locale: selectedLocale }
			});
			activateLocale(selectedLocale);
			notice = msg('Locale saved');
		} catch (reason) {
			error = reason instanceof Error ? reason.message : $t('Account action failed');
		} finally {
			busy = false;
		}
	}

	function revokeToken(tokenId: string) {
		void mutate(
			() => apiRequest(`/account/api-tokens/${tokenId}`, { method: 'DELETE' }),
			msg('API Token revoked')
		);
	}

	function revokeSession(sessionId: string, current: boolean) {
		if (current) {
			void navigateAfter(() => apiRequest(`/account/sessions/${sessionId}`, { method: 'DELETE' }));
			return;
		}
		void mutate(
			() => apiRequest(`/account/sessions/${sessionId}`, { method: 'DELETE' }),
			msg('Session revoked')
		);
	}

	async function revokeAllSessions() {
		await navigateAfter(() => apiRequest('/account/sessions', { method: 'DELETE' }));
	}

	async function logout() {
		await navigateAfter(() => apiRequest('/session', { method: 'DELETE' }));
	}
</script>

<div class="mb-8 flex flex-wrap items-end justify-between gap-4">
	<div>
		<p class="mb-2 text-xs font-bold tracking-[0.12em] text-primary-700 uppercase">
			{$t('Personal settings')}
		</p>
		<h1 class="mb-2">{$t('Account')}</h1>
		<p class="mb-0 text-surface-600">{$t('Sessions, API Tokens, locale, and password.')}</p>
	</div>
	<button class="btn preset-tonal-surface font-semibold" disabled={busy} onclick={logout}
		>{$t('Sign out')}</button
	>
</div>
{#if error}<p class="text-error-700" role="alert">{error}</p>{/if}
{#if notice}<p
		class="rounded-base border border-success-200 preset-tonal-success px-4 py-3 text-success-900"
		role="status"
	>
		{$t(notice)}
	</p>{/if}
{#if account.isPending}
	<p class="text-surface-600">{$t('Loading account…')}</p>
{:else if account.data}
	<section
		class="mb-4 flex flex-wrap items-center justify-between gap-4 rounded-xl border border-surface-300 bg-surface-50 p-5 shadow-sm"
	>
		<div class="flex min-w-0 items-center gap-3">
			<span
				class="grid size-11 shrink-0 place-items-center rounded-full bg-primary-50 text-lg font-bold text-primary-800"
				>{account.data.user.username.slice(0, 1).toUpperCase()}</span
			>
			<div class="min-w-0">
				<h2 class="m-0 truncate text-lg">{account.data.user.username}</h2>
				<p class="m-0 text-sm text-surface-600">{$t(domainLabel(account.data.user.role))}</p>
			</div>
		</div>
		<span class="badge preset-tonal-surface">{$t('Signed in')}</span>
	</section>
	<div class="grid items-start gap-4 xl:grid-cols-[minmax(18rem,0.8fr)_minmax(0,1.2fr)]">
		<div class="grid min-w-0 content-start gap-4">
			<section class="stack card border border-surface-300 bg-surface-50 p-5 shadow-sm">
				<div>
					<h2>{$t('Preferences')}</h2>
					<p class="mb-0 text-sm text-surface-600">
						{$t('Choose how Quirebase looks and speaks to you.')}
					</p>
				</div>
				<form class="stack" onsubmit={saveLocale}>
					<label
						>{$t('Language')}<select
							class="select"
							bind:value={selectedLocale}
							aria-label={$t('Locale')}
							><option value="en-US">English</option><option value="zh-CN">简体中文</option></select
						></label
					>
					<div>
						<button class="btn preset-tonal-surface font-semibold" disabled={busy}
							>{$t('Save locale')}</button
						>
					</div>
				</form>
				<label class="flex items-start gap-2 border-t border-surface-300 pt-4">
					<input type="checkbox" bind:checked={sidebarCollapsed} onchange={saveSidebarPreference} />
					<span
						><strong>{$t('Collapse navigation sidebar by default')}</strong><small
							class="block text-surface-600"
							>{$t('Free more horizontal space for reading and metadata work.')}</small
						></span
					>
				</label>
			</section>
			<section class="stack card border border-surface-300 bg-surface-50 p-5 shadow-sm">
				<div>
					<h2>{$t('Password')}</h2>
					<p class="mb-0 text-sm text-surface-600">
						{$t('Use at least 12 characters for a strong password.')}
					</p>
				</div>
				<form class="stack" onsubmit={changePassword}>
					<label
						>{$t('Current password')}<input
							class="input"
							name="current_password"
							type="password"
							autocomplete="current-password"
							required
						/></label
					>
					<label
						>{$t('New password')}<input
							class="input"
							name="new_password"
							type="password"
							autocomplete="new-password"
							minlength="12"
							required
						/></label
					>
					<div>
						<button class="btn preset-filled-primary-700-300 font-semibold" disabled={busy}
							>{$t('Change password')}</button
						>
					</div>
				</form>
			</section>
		</div>
		<div class="grid min-w-0 content-start gap-4">
			<section class="stack min-w-0 card border border-surface-300 bg-surface-50 p-5 shadow-sm">
				<div class="flex flex-wrap items-center justify-between gap-3">
					<div>
						<h2 class="mb-1">{$t('Sessions')}</h2>
						<p class="mb-0 text-sm text-surface-600">
							{account.data.sessions.length}
							{$t('active sessions')}
						</p>
					</div>
					<button
						class="btn preset-tonal-surface font-semibold"
						disabled={busy}
						onclick={revokeAllSessions}>{$t('Revoke all sessions')}</button
					>
				</div>
				<div class="divide-line divide-y">
					{#each account.data.sessions as session (session.id)}
						<div
							class="flex flex-wrap items-center justify-between gap-3 py-3 first:pt-0 last:pb-0"
						>
							<div class="min-w-0">
								<strong>{session.current ? $t('Current session') : $t('Session')}</strong>
								<p class="m-0 text-sm text-surface-600">
									{$t('Created')}
									{new Date(session.created_at).toLocaleString()}
								</p>
								<p class="m-0 text-xs text-surface-600">
									{$t('Expires')}
									{new Date(session.expires_at).toLocaleString()}
								</p>
							</div>
							<button
								class="btn shrink-0 preset-tonal-surface font-semibold"
								disabled={busy}
								onclick={() => revokeSession(session.id, session.current)}
								>{session.current ? $t('Revoke current session') : $t('Revoke session')}</button
							>
						</div>
					{:else}
						<p class="text-surface-600">{$t('No sessions.')}</p>
					{/each}
				</div>
			</section>
			<section
				class="stack min-w-0 overflow-hidden card border border-surface-300 bg-surface-50 p-5 shadow-sm"
			>
				<div>
					<h2 class="mb-1">{$t('API Tokens')}</h2>
					<p class="mb-0 text-sm text-surface-600">
						{$t('Create revocable credentials for API and MCP clients.')}
					</p>
				</div>
				<form
					class="grid min-w-0 gap-2 sm:grid-cols-[minmax(8rem,1fr)_8rem_auto]"
					onsubmit={(event) => {
						event.preventDefault();
						createToken();
					}}
				>
					<input
						class="input grow"
						bind:value={tokenName}
						placeholder={$t('Token name')}
						required
					/>
					<select class="select" bind:value={tokenDays} aria-label={$t('Expires after')}>
						<option value={7}>{$t('7 days')}</option><option value={30}>{$t('30 days')}</option
						><option value={90}>{$t('90 days')}</option><option value={365}>{$t('365 days')}</option
						>
					</select>
					<button class="btn preset-filled-primary-700-300 font-semibold" disabled={busy}
						>{$t('Create')}</button
					>
				</form>
				{#if createdToken}
					<div class="secret min-w-0" role="status">
						<strong>{$t('Copy this token now')}</strong><code>{createdToken}</code>
					</div>
				{/if}
				{#each account.data.api_tokens as token (token.id)}
					<div
						class="flex min-w-0 flex-wrap items-center justify-between gap-3 border-t border-surface-300 pt-3"
					>
						<div class="min-w-0">
							<strong class="block truncate">{token.name}</strong><span
								class="text-sm text-surface-600"
								>{$t(domainLabel(token.status))} · {$t('Expires')}
								{new Date(token.expires_at).toLocaleDateString()}</span
							>
						</div>
						<button
							class="btn shrink-0 preset-tonal-surface font-semibold"
							disabled={busy}
							onclick={() => revokeToken(token.id)}>{$t('Revoke token')}</button
						>
					</div>
				{:else}
					<p class="text-surface-600">{$t('No API Tokens.')}</p>
				{/each}
				<details class="mt-2 min-w-0 border-t border-surface-300 pt-4">
					<summary class="cursor-pointer font-semibold">{$t('Client connection guide')}</summary>
					<div class="mt-4 min-w-0">
						<h3>{$t('Connect an HTTP API client')}</h3>
						<p class="text-sm text-surface-600">
							{$t(
								'Use the versioned JSON API and send your API Token in the Authorization header.'
							)}
						</p>
						<dl class="grid min-w-0 gap-3 text-sm sm:grid-cols-[7rem_minmax(0,1fr)]">
							<div>
								<dt>{$t('Base endpoint')}</dt>
								<dd class="m-0 break-all"><code>{externalOrigin}/api/v1</code></dd>
							</div>
							<div>
								<dt>{$t('OpenAPI')}</dt>
								<dd class="m-0 break-all">
									<button
										class="cursor-pointer border-0 bg-transparent p-0 underline"
										onclick={() => location.assign(`${externalOrigin}/docs`)}
										><code>{externalOrigin}/docs</code></button
									>
								</dd>
							</div>
							<div>
								<dt>{$t('Header')}</dt>
								<dd class="m-0 break-all"><code>Authorization: Bearer YOUR_API_TOKEN</code></dd>
							</div>
						</dl>
						<pre
							class="overflow-x-auto rounded-lg border border-surface-300 bg-surface-200 p-3 text-xs"><code
								>curl \
  -H 'Authorization: Bearer YOUR_API_TOKEN' \
  '{externalOrigin}/api/v1/items'</code
							></pre>
					</div>
					<div class="mt-4 border-t border-surface-300 pt-4">
						<h3>{$t('Connect an MCP client')}</h3>
						<p class="text-sm text-surface-600">
							{$t('Use Streamable HTTP. Never put an API Token in the URL.')}
						</p>
						<pre
							class="overflow-x-auto rounded-lg border border-surface-300 bg-surface-200 p-3 text-xs"><code
								>{`{
  "mcpServers": {
    "quirebase": {
      "url": "${externalOrigin}/mcp",
      "headers": {"Authorization": "Bearer YOUR_API_TOKEN"}
    }
  }
}`}</code
							></pre>
					</div>
				</details>
			</section>
		</div>
	</div>
	<div class="mt-4"><ExportPreferences userId={account.data.user.id} /></div>
{/if}
