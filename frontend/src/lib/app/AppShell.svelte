<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { Menu, Portal } from '@skeletonlabs/skeleton-svelte';
	import { createQuery } from '@tanstack/svelte-query';
	import { onMount, type Snippet } from 'svelte';
	import { apiRequest, onAuthenticationRequired } from '$lib/api/client';
	import { apiErrorMessage } from '$lib/api/errors';
	import Icon from '$lib/design/Icon.svelte';
	import Notice from '$lib/design/Notice.svelte';
	import Toast from '$lib/design/Toast.svelte';
	import { domainLabel } from '$lib/domain-labels';
	import { activateLocale, msg, t } from '$lib/i18n';
	import Login from '$lib/features/auth/Login.svelte';
	import { sessionQuery, setSession } from '$lib/session';
	import { WorkflowCenter, setWorkflowCenter } from '$lib/features/workflows/center.svelte';
	import { localStorageWorkflowLedger } from '$lib/features/workflows/ledger';
	import WorkflowTray from '$lib/features/workflows/WorkflowTray.svelte';
	import {
		applyTheme,
		readThemePreference,
		saveThemePreference,
		type ThemePreference
	} from '$lib/theme';

	let { children } = $props<{ children: Snippet }>();

	const session = createQuery(() => sessionQuery());
	setSession({ query: session, logout });
	const workflowCenter = new WorkflowCenter();
	setWorkflowCenter(workflowCenter);
	let ledgerUserId = '';
	$effect(() => {
		const userId = session.data?.user?.id;
		if (!userId || userId === ledgerUserId) return;
		ledgerUserId = userId;
		workflowCenter.bindLedger(localStorageWorkflowLedger(userId));
	});
	const nav = [
		['/', msg('Dashboard'), 'dashboard'],
		['/library', msg('Library'), 'library'],
		['/import', msg('Import'), 'import'],
		['/discovery', msg('Discovery'), 'search'],
		['/projects', msg('Projects'), 'projects'],
		['/tools', msg('Tools'), 'tools']
	] as const;
	const mobileNav = [
		['/library', msg('Library'), 'library'],
		['/discovery', msg('Discovery'), 'search'],
		['/projects', msg('Projects'), 'projects']
	] as const;
	const mobileMoreNav = [
		['/', msg('Dashboard'), 'dashboard'],
		['/import', msg('Import'), 'import'],
		['/tools', msg('Tools'), 'tools'],
		['/account', msg('Account settings'), 'user']
	] as const;
	const themeOptions = [
		['system', msg('System theme'), 'monitor'],
		['light', msg('Light theme'), 'sun'],
		['dark', msg('Dark theme'), 'moon']
	] as const;
	const routeIsActive = (route: string) =>
		route === '/' ? page.url.pathname === route : page.url.pathname.startsWith(route);
	const readerRoute = $derived(/\/item\/[^/]+\/pdf\/[^/]+$/.test(page.url.pathname));
	let sidebarCollapsed = $state(false);
	let actionError = $state('');
	let actionBusy = $state(false);
	let themePreference = $state<ThemePreference>('system');
	let colorSchemeQuery: MediaQueryList | undefined;
	onMount(() => {
		const unregisterAuthenticationHandler = onAuthenticationRequired(() => {
			void session.refetch();
		});
		sidebarCollapsed = localStorage.getItem('quirebase:sidebar-collapsed') === 'true';
		themePreference = readThemePreference();
		colorSchemeQuery = matchMedia('(prefers-color-scheme: dark)');
		applyTheme(themePreference, colorSchemeQuery.matches);
		const handleColorSchemeChange = () => {
			if (themePreference === 'system' && colorSchemeQuery)
				applyTheme(themePreference, colorSchemeQuery.matches);
		};
		colorSchemeQuery.addEventListener('change', handleColorSchemeChange);
		return () => {
			unregisterAuthenticationHandler();
			colorSchemeQuery?.removeEventListener('change', handleColorSchemeChange);
		};
	});
	function toggleSidebar() {
		sidebarCollapsed = !sidebarCollapsed;
		localStorage.setItem('quirebase:sidebar-collapsed', String(sidebarCollapsed));
	}
	function setThemePreference(preference: ThemePreference) {
		themePreference = preference;
		saveThemePreference(preference);
		applyTheme(preference, colorSchemeQuery?.matches ?? false);
	}
	async function logout() {
		if (actionBusy) return;
		actionBusy = true;
		actionError = '';
		try {
			await apiRequest('DELETE', '/session');
			location.assign('/');
		} catch (reason) {
			actionError = apiErrorMessage(reason, $t('Account action failed'));
		} finally {
			actionBusy = false;
		}
	}
	$effect(() => {
		if (session.data?.locale) activateLocale(session.data.locale);
	});
</script>

{#if session.isPending}
	<main class="mx-auto w-full max-w-[100rem] min-w-0 p-4 md:p-[clamp(1.25rem,3vw,2.75rem)]">
		<p class="text-surface-600-400">{$t('Loading Quirebase…')}</p>
	</main>
{:else if !session.data?.authenticated}
	<Login />
{:else}
	<WorkflowTray />
	<div
		class={`sticky top-0 z-40 items-center justify-between bg-primary-950 px-4 py-3 text-white md:hidden ${readerRoute ? 'hidden' : 'flex'}`}
	>
		<a class="flex items-center gap-2 font-bold no-underline" href={resolve('/')}
			><span
				class="grid size-7 grid-cols-1 place-items-center rounded-lg bg-white text-sm font-extrabold text-primary-800"
				>Q</span
			>
			Quirebase</a
		>
		<a
			class="grid size-8 grid-cols-1 place-items-center rounded-full bg-primary-100 font-extrabold text-primary-800 no-underline"
			href={resolve('/account')}>{session.data.user?.username.slice(0, 1).toUpperCase()}</a
		>
	</div>
	<div
		class={`min-h-screen md:grid ${sidebarCollapsed ? 'md:grid-cols-[4.75rem_minmax(0,1fr)]' : 'md:grid-cols-[15.5rem_minmax(0,1fr)]'} ${readerRoute ? '' : 'pb-16 md:pb-0'}`}
	>
		<aside
			class={`sticky top-0 hidden h-screen flex-col gap-4 bg-primary-950 py-5 text-primary-50 transition-[padding] md:flex ${sidebarCollapsed ? 'px-2.5' : 'px-3.5'}`}
		>
			<div class="flex items-center gap-1 pb-3">
				<a
					class={`flex min-w-0 flex-1 items-center gap-3 text-xl font-extrabold tracking-tight text-white no-underline ${sidebarCollapsed ? 'justify-center' : 'px-2'}`}
					href={resolve('/')}
					><span
						class="grid size-8 shrink-0 grid-cols-1 place-items-center rounded-xl bg-primary-50 font-serif text-xl text-primary-800"
						>Q</span
					>{#if !sidebarCollapsed}<span>Quirebase</span>{/if}</a
				>
				{#if !sidebarCollapsed}<button
						type="button"
						class="grid size-8 shrink-0 cursor-pointer grid-cols-1 place-items-center rounded-md border-0 bg-transparent text-surface-400 hover:bg-white/10 hover:text-white"
						aria-label={$t('Collapse sidebar')}
						onclick={toggleSidebar}><Icon name="chevron-left" size={16} /></button
					>{/if}
			</div>
			{#if sidebarCollapsed}<button
					type="button"
					class="mx-auto grid size-8 cursor-pointer grid-cols-1 place-items-center rounded-md border-0 bg-white/7 text-surface-400 hover:bg-white/12 hover:text-white"
					aria-label={$t('Expand sidebar')}
					onclick={toggleSidebar}><Icon name="chevron-right" size={16} /></button
				>{:else}<p
					class="mx-3 mt-1 text-[0.68rem] font-bold tracking-[0.11em] text-surface-400 uppercase"
				>
					{$t('Workspace')}
				</p>{/if}
			<nav class="grid grid-cols-1 gap-1" aria-label={$t('Main navigation')}>
				{#each nav as [route, label, icon] (route)}
					<a
						class="flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-semibold text-surface-400 no-underline transition-colors hover:bg-white/9 hover:text-white aria-[current=page]:bg-white/10 aria-[current=page]:text-white"
						href={resolve(route)}
						title={sidebarCollapsed ? $t(label) : undefined}
						aria-current={routeIsActive(route) ? 'page' : undefined}
						><Icon name={icon} />{#if !sidebarCollapsed}<span>{$t(label)}</span>{/if}</a
					>
				{/each}
				{#if session.data.user?.role === 'administrator'}
					<a
						class="flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-semibold text-surface-400 no-underline transition-colors hover:bg-white/9 hover:text-white aria-[current=page]:bg-white/10 aria-[current=page]:text-white"
						href={resolve('/admin')}
						title={sidebarCollapsed ? $t('Administration') : undefined}
						aria-current={routeIsActive('/admin') ? 'page' : undefined}
						><Icon name="admin" />{#if !sidebarCollapsed}<span>{$t('Administration')}</span>{/if}</a
					>
				{/if}
			</nav>
			<div class="mt-auto border-t border-white/12 pt-3.5">
				<Menu positioning={{ placement: 'top-start', gutter: 8 }}>
					<Menu.Trigger
						class="flex w-full cursor-pointer items-center gap-2.5 rounded-lg border-0 bg-white/7 p-2 text-white transition-colors hover:bg-white/12"
					>
						<span
							class="grid size-8 shrink-0 grid-cols-1 place-items-center rounded-full bg-primary-100 font-extrabold text-primary-800"
							>{session.data.user?.username.slice(0, 1).toUpperCase()}</span
						>
						{#if !sidebarCollapsed}<span class="grid min-w-0 flex-1 grid-cols-1 text-left"
								><strong class="truncate text-sm">{session.data.user?.username}</strong><small
									class="truncate text-xs text-surface-400"
									>{$t(domainLabel(session.data.user!.role))}</small
								></span
							>
							<Icon name="chevron-down" size={15} />{/if}
					</Menu.Trigger>
					<Portal>
						<Menu.Positioner class="z-100">
							<Menu.Content
								class="min-w-56 rounded-container border border-surface-300-700 bg-surface-50-950 p-1 shadow-xl"
							>
								<Menu.Item
									value="account-settings"
									class="flex cursor-pointer items-center gap-2 rounded-md px-2.5 py-2 text-sm outline-none data-[highlighted]:bg-primary-50-950 data-[highlighted]:text-primary-800-200"
									onclick={() => goto(resolve('/account'))}
									><Icon name="user" /> {$t('Account settings')}</Menu.Item
								>
								<Menu.Separator class="m-1 h-px bg-surface-300-700" />
								<div
									class="px-2.5 py-1.5 text-xs font-bold tracking-wide text-surface-600-400 uppercase"
								>
									{$t('Appearance')}
								</div>
								{#each themeOptions as [preference, label, icon] (preference)}
									<Menu.Item
										value={`theme-${preference}`}
										class="flex cursor-pointer items-center gap-2 rounded-md px-2.5 py-2 text-sm outline-none data-[active=true]:bg-primary-50-950 data-[active=true]:text-primary-800-200 data-[highlighted]:bg-primary-50-950 data-[highlighted]:text-primary-800-200"
										data-active={themePreference === preference}
										onclick={() => setThemePreference(preference)}
										><Icon name={icon} />
										<span>{$t(label)}</span>{#if themePreference === preference}<span
												class="ml-auto"
												aria-hidden="true">✓</span
											>{/if}</Menu.Item
									>
								{/each}
								<Menu.Separator class="m-1 h-px bg-surface-300-700" />
								<Menu.Item
									value="sign-out"
									class="flex cursor-pointer items-center rounded-md px-2.5 py-2 text-sm text-error-700-300 outline-none data-[highlighted]:bg-error-50-950"
									disabled={actionBusy}
									onclick={logout}>{$t('Sign out')}</Menu.Item
								>
							</Menu.Content>
						</Menu.Positioner>
					</Portal>
				</Menu>
			</div>
		</aside>
		<main
			class={readerRoute
				? 'mx-auto min-h-0 w-full max-w-[100rem] min-w-0'
				: 'mx-auto w-full max-w-[100rem] min-w-0 p-4 md:p-[clamp(1.25rem,3vw,2.75rem)]'}
		>
			{#if actionError}<Notice variant="error">{actionError}</Notice>{/if}
			{@render children()}
		</main>
	</div>
	<nav
		class={`fixed inset-x-0 bottom-0 z-50 overflow-x-auto bg-primary-950 text-surface-300 md:hidden ${readerRoute ? 'hidden' : 'flex'}`}
		aria-label={$t('Mobile navigation')}
	>
		{#each mobileNav as [route, label, icon] (route)}
			<a
				class="flex min-w-18 flex-1 flex-col items-center gap-1 px-1.5 py-2 text-xs no-underline aria-[current=page]:bg-white/10 aria-[current=page]:text-white"
				href={resolve(route)}
				aria-current={route === '/library'
					? routeIsActive(route) || page.url.pathname.startsWith('/item/')
						? 'page'
						: undefined
					: routeIsActive(route)
						? 'page'
						: undefined}><Icon name={icon} size={19} /><span>{$t(label)}</span></a
			>
		{/each}
		<Menu positioning={{ placement: 'top-end', gutter: 8 }}>
			<Menu.Trigger
				class="flex min-w-18 flex-1 cursor-pointer flex-col items-center gap-1 border-0 bg-transparent px-1.5 py-2 text-xs text-inherit aria-[current=page]:bg-white/10 aria-[current=page]:text-white"
				aria-current={['/', '/import', '/tools', '/admin', '/account'].some((route) =>
					routeIsActive(route)
				)
					? 'page'
					: undefined}
			>
				<Icon name="more" size={19} /><span>{$t('More')}</span>
			</Menu.Trigger>
			<Portal>
				<Menu.Positioner class="z-100">
					<Menu.Content
						class="min-w-52 rounded-container border border-surface-300-700 bg-surface-50-950 p-1 text-surface-900-100 shadow-xl"
					>
						{#each mobileMoreNav as [route, label, icon] (route)}
							<Menu.Item
								value={route}
								class="flex cursor-pointer items-center gap-2 rounded-md px-2.5 py-2 text-sm outline-none data-[highlighted]:bg-primary-50-950 data-[highlighted]:text-primary-800-200"
								onclick={() => goto(resolve(route))}><Icon name={icon} /> {$t(label)}</Menu.Item
							>
						{/each}
						<Menu.Separator class="m-1 h-px bg-surface-300-700" />
						<div
							class="px-2.5 py-1.5 text-xs font-bold tracking-wide text-surface-600-400 uppercase"
						>
							{$t('Appearance')}
						</div>
						{#each themeOptions as [preference, label, icon] (preference)}
							<Menu.Item
								value={`mobile-theme-${preference}`}
								class="flex cursor-pointer items-center gap-2 rounded-md px-2.5 py-2 text-sm outline-none data-[active=true]:bg-primary-50-950 data-[active=true]:text-primary-800-200 data-[highlighted]:bg-primary-50-950 data-[highlighted]:text-primary-800-200"
								data-active={themePreference === preference}
								onclick={() => setThemePreference(preference)}
								><Icon name={icon} />
								<span>{$t(label)}</span>{#if themePreference === preference}<span
										class="ml-auto"
										aria-hidden="true">✓</span
									>{/if}</Menu.Item
							>
						{/each}
						{#if session.data.user?.role === 'administrator'}
							<Menu.Item
								value="/admin"
								class="flex cursor-pointer items-center gap-2 rounded-md px-2.5 py-2 text-sm outline-none data-[highlighted]:bg-primary-50-950 data-[highlighted]:text-primary-800-200"
								onclick={() => goto(resolve('/admin'))}
								><Icon name="admin" /> {$t('Administration')}</Menu.Item
							>
						{/if}
					</Menu.Content>
				</Menu.Positioner>
			</Portal>
		</Menu>
	</nav>
{/if}
<Toast />
