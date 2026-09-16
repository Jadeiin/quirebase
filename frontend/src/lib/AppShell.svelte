<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { createQuery } from '@tanstack/svelte-query';
	import { DropdownMenu } from 'bits-ui';
	import { onMount, type Snippet } from 'svelte';
	import { apiRequest, type SessionView } from '$lib/api/client';
	import Icon from '$lib/design/Icon.svelte';
	import { domainLabel } from '$lib/domain-labels';
	import { activateLocale, msg, t } from '$lib/i18n';
	import Login from '$lib/Login.svelte';

	let { children } = $props<{ children: Snippet }>();

	const session = createQuery(() => ({
		queryKey: ['session'],
		queryFn: () => apiRequest<SessionView>('/session'),
		retry: false
	}));
	const nav = [
		['/', msg('Dashboard'), 'dashboard'],
		['/library', msg('Library'), 'library'],
		['/import', msg('Import'), 'import'],
		['/discovery', msg('Discovery'), 'search'],
		['/projects', msg('Projects'), 'projects'],
		['/tools', msg('Tools'), 'tools']
	] as const;
	const routeIsActive = (route: string) =>
		route === '/' ? page.url.pathname === route : page.url.pathname.startsWith(route);
	const readerRoute = $derived(/\/item\/[^/]+\/pdf\/[^/]+$/.test(page.url.pathname));
	let sidebarCollapsed = $state(false);
	let actionError = $state('');
	let actionBusy = $state(false);
	onMount(() => {
		sidebarCollapsed = localStorage.getItem('quirebase:sidebar-collapsed') === 'true';
	});
	function toggleSidebar() {
		sidebarCollapsed = !sidebarCollapsed;
		localStorage.setItem('quirebase:sidebar-collapsed', String(sidebarCollapsed));
	}
	async function logout() {
		if (actionBusy) return;
		actionBusy = true;
		actionError = '';
		try {
			await apiRequest('/session', { method: 'DELETE' });
			location.assign('/');
		} catch (reason) {
			actionError = reason instanceof Error ? reason.message : $t('Account action failed');
		} finally {
			actionBusy = false;
		}
	}
	$effect(() => {
		if (session.data?.locale) activateLocale(session.data.locale);
	});
</script>

{#if session.isPending}
	<main class="workspace"><p class="muted">{$t('Loading Quirebase…')}</p></main>
{:else if !session.data?.authenticated}
	<Login />
{:else}
	<div
		class={`sticky top-0 z-40 items-center justify-between bg-sidebar px-4 py-3 text-white md:hidden ${readerRoute ? 'hidden' : 'flex'}`}
	>
		<a class="flex items-center gap-2 font-bold no-underline" href={resolve('/')}
			><span
				class="grid size-7 place-items-center rounded-lg bg-white text-sm font-extrabold text-accent-strong"
				>Q</span
			>
			Quirebase</a
		>
		<a
			class="grid size-8 place-items-center rounded-full bg-[#d7eee3] font-extrabold text-accent-strong no-underline"
			href={resolve('/account')}>{session.data.user?.username.slice(0, 1).toUpperCase()}</a
		>
	</div>
	<div
		class={`min-h-screen md:grid ${sidebarCollapsed ? 'md:grid-cols-[4.75rem_minmax(0,1fr)]' : 'md:grid-cols-[15.5rem_minmax(0,1fr)]'} ${readerRoute ? '' : 'pb-16 md:pb-0'}`}
	>
		<aside
			class={`sticky top-0 hidden h-screen flex-col gap-4 bg-sidebar py-5 text-[#edf5f1] transition-[padding] md:flex ${sidebarCollapsed ? 'px-2.5' : 'px-3.5'}`}
		>
			<div class="flex items-center gap-1 pb-3">
				<a
					class={`flex min-w-0 flex-1 items-center gap-3 text-xl font-extrabold tracking-tight text-white no-underline ${sidebarCollapsed ? 'justify-center' : 'px-2'}`}
					href={resolve('/')}
					><span
						class="grid size-8 shrink-0 place-items-center rounded-xl bg-[#f1faf5] font-serif text-xl text-accent-strong"
						>Q</span
					>{#if !sidebarCollapsed}<span>Quirebase</span>{/if}</a
				>
				{#if !sidebarCollapsed}<button
						type="button"
						class="grid size-8 shrink-0 cursor-pointer place-items-center rounded-md border-0 bg-transparent text-sidebar-muted hover:bg-white/10 hover:text-white"
						aria-label={$t('Collapse sidebar')}
						onclick={toggleSidebar}><Icon name="chevron-left" size={16} /></button
					>{/if}
			</div>
			{#if sidebarCollapsed}<button
					type="button"
					class="mx-auto grid size-8 cursor-pointer place-items-center rounded-md border-0 bg-white/7 text-sidebar-muted hover:bg-white/12 hover:text-white"
					aria-label={$t('Expand sidebar')}
					onclick={toggleSidebar}><Icon name="chevron-right" size={16} /></button
				>{:else}<p
					class="mx-3 mt-1 text-[0.68rem] font-bold tracking-[0.11em] text-sidebar-muted uppercase"
				>
					{$t('Workspace')}
				</p>{/if}
			<nav class="grid gap-1" aria-label={$t('Main navigation')}>
				{#each nav as [route, label, icon] (route)}
					<a
						class="flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-semibold text-sidebar-muted no-underline transition-colors hover:bg-white/9 hover:text-white aria-[current=page]:bg-white/10 aria-[current=page]:text-white"
						href={resolve(route)}
						title={sidebarCollapsed ? $t(label) : undefined}
						aria-current={routeIsActive(route) ? 'page' : undefined}
						><Icon name={icon} />{#if !sidebarCollapsed}<span>{$t(label)}</span>{/if}</a
					>
				{/each}
				{#if session.data.user?.role === 'administrator'}
					<a
						class="flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-semibold text-sidebar-muted no-underline transition-colors hover:bg-white/9 hover:text-white aria-[current=page]:bg-white/10 aria-[current=page]:text-white"
						href={resolve('/admin')}
						title={sidebarCollapsed ? $t('Administration') : undefined}
						aria-current={routeIsActive('/admin') ? 'page' : undefined}
						><Icon name="admin" />{#if !sidebarCollapsed}<span>{$t('Administration')}</span>{/if}</a
					>
				{/if}
			</nav>
			<div class="mt-auto border-t border-white/12 pt-3.5">
				<DropdownMenu.Root>
					<DropdownMenu.Trigger
						class="flex w-full cursor-pointer items-center gap-2.5 rounded-lg border-0 bg-white/7 p-2 text-white transition-colors hover:bg-white/12"
					>
						<span
							class="grid size-8 shrink-0 place-items-center rounded-full bg-[#d7eee3] font-extrabold text-accent-strong"
							>{session.data.user?.username.slice(0, 1).toUpperCase()}</span
						>
						{#if !sidebarCollapsed}<span class="grid min-w-0 flex-1 text-left"
								><strong class="truncate text-sm">{session.data.user?.username}</strong><small
									class="truncate text-xs text-sidebar-muted"
									>{$t(domainLabel(session.data.user!.role))}</small
								></span
							>
							<Icon name="chevron-down" size={15} />{/if}
					</DropdownMenu.Trigger>
					<DropdownMenu.Portal>
						<DropdownMenu.Content
							class="z-100 min-w-56 rounded-lg border border-line bg-raised p-1 shadow-xl"
							sideOffset={8}
							align="start"
						>
							<DropdownMenu.Item
								class="flex cursor-pointer items-center gap-2 rounded-md px-2.5 py-2 text-sm outline-none data-[highlighted]:bg-accent-soft data-[highlighted]:text-accent-strong"
								onclick={() => location.assign(resolve('/account'))}
								><Icon name="user" /> {$t('Account settings')}</DropdownMenu.Item
							>
							<DropdownMenu.Separator class="m-1 h-px bg-line" />
							<DropdownMenu.Item
								class="flex cursor-pointer items-center rounded-md px-2.5 py-2 text-sm text-danger outline-none data-[highlighted]:bg-red-50"
								disabled={actionBusy}
								onclick={logout}>{$t('Sign out')}</DropdownMenu.Item
							>
						</DropdownMenu.Content>
					</DropdownMenu.Portal>
				</DropdownMenu.Root>
			</div>
		</aside>
		<main
			class={readerRoute
				? 'mx-auto min-h-0 w-full max-w-[100rem] min-w-0'
				: 'mx-auto w-full max-w-[100rem] min-w-0 p-4 md:p-[clamp(1.25rem,3vw,2.75rem)]'}
		>
			{#if actionError}<p class="error" role="alert">{actionError}</p>{/if}
			{@render children()}
		</main>
	</div>
	<nav
		class={`fixed inset-x-0 bottom-0 z-50 overflow-x-auto bg-sidebar text-[#dbe4f0] md:hidden ${readerRoute ? 'hidden' : 'flex'}`}
		aria-label={$t('Mobile navigation')}
	>
		{#each nav as [route, label, icon] (route)}
			<a
				class="flex min-w-20 flex-1 flex-col items-center gap-1 px-1.5 py-2 text-xs no-underline aria-[current=page]:bg-white/10 aria-[current=page]:text-white"
				href={resolve(route)}
				aria-current={routeIsActive(route) ? 'page' : undefined}
				><Icon name={icon} size={19} /><span>{$t(label)}</span></a
			>
		{/each}
		{#if session.data.user?.role === 'administrator'}
			<a
				class="flex min-w-20 flex-1 flex-col items-center gap-1 px-1.5 py-2 text-xs no-underline aria-[current=page]:bg-white/10 aria-[current=page]:text-white"
				href={resolve('/admin')}
				aria-current={routeIsActive('/admin') ? 'page' : undefined}
				><Icon name="admin" size={19} /><span>{$t('Administration')}</span></a
			>
		{/if}
	</nav>
{/if}
