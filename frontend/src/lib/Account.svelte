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

<div class="workspace-header">
	<div>
		<h1>{$t('Account')}</h1>
		<p class="muted">{$t('Sessions, API Tokens, locale, and password.')}</p>
	</div>
	<button class="button" disabled={busy} onclick={logout}>{$t('Sign out')}</button>
</div>
{#if error}<p class="error" role="alert">{error}</p>{/if}
{#if notice}<p class="notice" role="status">{$t(notice)}</p>{/if}
{#if account.isPending}
	<p class="muted">{$t('Loading account…')}</p>
{:else if account.data}
	<div class="dashboard-grid">
		<section class="panel stack">
			<div>
				<h2>{account.data.user.username}</h2>
				<p class="muted">{$t(domainLabel(account.data.user.role))}</p>
			</div>
			<form class="stack" onsubmit={changePassword}>
				<h3>{$t('Password')}</h3>
				<label
					>{$t('Current password')}<input
						class="field"
						name="current_password"
						type="password"
						autocomplete="current-password"
						required
					/></label
				>
				<label
					>{$t('New password')}<input
						class="field"
						name="new_password"
						type="password"
						autocomplete="new-password"
						minlength="12"
						required
					/></label
				>
				<button class="button button-primary" disabled={busy}>{$t('Change password')}</button>
			</form>
			<form class="stack" onsubmit={saveLocale}>
				<h3>{$t('Language')}</h3>
				<label
					>{$t('Locale')}<select class="field" bind:value={selectedLocale}
						><option value="en-US">English</option><option value="zh-CN">简体中文</option></select
					></label
				>
				<button class="button" disabled={busy}>{$t('Save locale')}</button>
			</form>
			<label class="flex items-start gap-2">
				<input type="checkbox" bind:checked={sidebarCollapsed} onchange={saveSidebarPreference} />
				<span
					><strong>{$t('Collapse navigation sidebar by default')}</strong><small
						class="block text-muted"
						>{$t('Free more horizontal space for reading and metadata work.')}</small
					></span
				>
			</label>
		</section>
		<section class="panel stack">
			<div class="workspace-header">
				<h2>{$t('Sessions')}</h2>
				<button class="button" disabled={busy} onclick={revokeAllSessions}
					>{$t('Revoke all sessions')}</button
				>
			</div>
			{#each account.data.sessions as session (session.id)}
				<div class="item-row">
					<strong>{session.current ? $t('Current session') : $t('Session')}</strong>
					<span class="muted"
						>{$t('Created')}
						{new Date(session.created_at).toLocaleString()} · {$t('expires')}
						{new Date(session.expires_at).toLocaleString()}</span
					>
					<button
						class="button"
						disabled={busy}
						onclick={() => revokeSession(session.id, session.current)}
						>{session.current ? $t('Revoke current session') : $t('Revoke session')}</button
					>
				</div>
			{:else}
				<p class="muted">{$t('No sessions.')}</p>
			{/each}
		</section>
		<section class="panel stack">
			<h2>{$t('API Tokens')}</h2>
			<form
				class="grid gap-2 sm:grid-cols-[minmax(10rem,1fr)_9rem_auto]"
				onsubmit={(event) => {
					event.preventDefault();
					createToken();
				}}
			>
				<input class="field grow" bind:value={tokenName} placeholder={$t('Token name')} required />
				<select class="field" bind:value={tokenDays} aria-label={$t('Expires after')}>
					<option value={7}>{$t('7 days')}</option><option value={30}>{$t('30 days')}</option
					><option value={90}>{$t('90 days')}</option><option value={365}>{$t('365 days')}</option>
				</select>
				<button class="button button-primary" disabled={busy}>{$t('Create')}</button>
			</form>
			{#if createdToken}
				<div class="secret" role="status">
					<strong>{$t('Copy this token now')}</strong><code>{createdToken}</code>
				</div>
			{/if}
			{#each account.data.api_tokens as token (token.id)}
				<div class="item-row">
					<strong>{token.name}</strong><span class="muted"
						>{$t(domainLabel(token.status))} · {$t('expires')}
						{new Date(token.expires_at).toLocaleDateString()}</span
					><button class="button" disabled={busy} onclick={() => revokeToken(token.id)}
						>{$t('Revoke token')}</button
					>
				</div>
			{:else}
				<p class="muted">{$t('No API Tokens.')}</p>
			{/each}
			<div class="mt-3 border-t border-line pt-4">
				<h3>{$t('Connect an HTTP API client')}</h3>
				<p class="muted text-sm">
					{$t('Use the versioned JSON API and send your API Token in the Authorization header.')}
				</p>
				<dl class="metadata-grid text-sm">
					<div>
						<dt>{$t('Base endpoint')}</dt>
						<dd><code>{externalOrigin}/api/v1</code></dd>
					</div>
					<div>
						<dt>{$t('OpenAPI')}</dt>
						<dd>
							<button
								class="cursor-pointer border-0 bg-transparent p-0 underline"
								onclick={() => location.assign(`${externalOrigin}/docs`)}
								><code>{externalOrigin}/docs</code></button
							>
						</dd>
					</div>
					<div>
						<dt>{$t('Header')}</dt>
						<dd><code>Authorization: Bearer YOUR_API_TOKEN</code></dd>
					</div>
				</dl>
				<pre
					class="overflow-x-auto rounded-lg border border-line bg-muted-surface p-3 text-xs"><code
						>curl \
  -H 'Authorization: Bearer YOUR_API_TOKEN' \
  '{externalOrigin}/api/v1/items'</code
					></pre>
			</div>
			<div class="mt-3 border-t border-line pt-4">
				<h3>{$t('Connect an MCP client')}</h3>
				<p class="muted text-sm">
					{$t('Use Streamable HTTP. Never put an API Token in the URL.')}
				</p>
				<pre
					class="overflow-x-auto rounded-lg border border-line bg-muted-surface p-3 text-xs"><code
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
		</section>
	</div>
	<div class="mt-4"><ExportPreferences userId={account.data.user.id} /></div>
{/if}
