<script lang="ts">
	import type { HTMLAttributes } from 'svelte/elements';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { Menu, Navigation, Portal } from '@skeletonlabs/skeleton-svelte';
	import type { components } from '#lib/api/schema.js';
	import { hasAllowedAction } from '#lib/authorization/can.js';
	import Icon from '#lib/design/Icon.svelte';
	import { t } from '#lib/i18n.js';
	import type { ThemePreference } from '#lib/theme.js';
	import { mobileMoreNavigation, mobileNavigation, themeOptions } from './navigation';
	import { workspaceHref } from '#lib/workspaces/href.js';

	let {
		routeIsActive,
		user,
		readerRoute,
		themePreference,
		onThemeChange,
		workspaceId
	}: {
		routeIsActive: (route: string) => boolean;
		user?: components['schemas']['SessionUserView'] | null;
		readerRoute: boolean;
		workspaceId?: string;
		themePreference: ThemePreference;
		onThemeChange: (preference: ThemePreference) => void;
	} = $props();
	const mobileItems = $derived(
		(workspaceId ? mobileNavigation : []).map(
			([section, label, icon]) =>
				[
					workspaceId ? resolve(workspaceHref(workspaceId, section)) : resolve('workspace'),
					label,
					icon
				] as const
		)
	);
	const moreItems = $derived(
		mobileMoreNavigation
			.filter(([section]) => workspaceId || section === '/account')
			.map(
				([section, label, icon]) =>
					[
						section === '/account'
							? resolve('account')
							: workspaceId
								? resolve(workspaceHref(workspaceId, section))
								: resolve('workspace'),
						label,
						icon
					] as const
			)
	);
	const moreActive = $derived(
		moreItems.some(([route]) =>
			route === '/account' ? routeIsActive(route) : Boolean(workspaceId) && routeIsActive(route)
		)
	);
</script>

<Navigation
	layout="bar"
	class={`fixed inset-x-0 bottom-0 z-50 overflow-x-auto bg-primary-950 p-0 text-surface-300 md:hidden ${readerRoute ? 'hidden' : 'flex'}`}
>
	{#snippet element(attributes)}
		<nav {...attributes as HTMLAttributes<HTMLElement>} aria-label={$t('Mobile navigation')}>
			<Navigation.Menu class="w-full gap-0">
				{#if !workspaceId}<Navigation.TriggerAnchor
						class="flex min-w-18 flex-1 flex-col items-center gap-1 rounded-none bg-transparent px-1.5 py-2 text-xs no-underline aria-[current=page]:bg-white/10 aria-[current=page]:text-white"
						href={resolve('workspace')}
						aria-current={routeIsActive('/workspace') ? 'page' : undefined}
					>
						<Icon name="panel" size={19} /><span>{$t('My workspaces')}</span>
					</Navigation.TriggerAnchor>{/if}
				{#each mobileItems as [route, label, icon] (label)}
					<Navigation.TriggerAnchor
						class="flex min-w-18 flex-1 flex-col items-center gap-1 rounded-none bg-transparent px-1.5 py-2 text-xs no-underline aria-[current=page]:bg-white/10 aria-[current=page]:text-white"
						href={route}
						aria-current={workspaceId &&
							(route.endsWith('/library')
								? routeIsActive(route) || page.url.pathname.includes('/item/')
									? 'page'
									: undefined
								: routeIsActive(route)
									? 'page'
									: undefined)}
					>
						<Icon name={icon} size={19} />
						<span class="min-w-0 flex-1">{$t(label)}</span>
					</Navigation.TriggerAnchor>
				{/each}
				<Menu positioning={{ placement: 'top-end', gutter: 8 }}>
					<Menu.Trigger
						class="flex min-w-18 flex-1 cursor-pointer flex-col items-center gap-1 border-0 bg-transparent px-1.5 py-2 text-xs text-inherit aria-[current=page]:bg-white/10 aria-[current=page]:text-white"
						aria-current={moreActive ? 'page' : undefined}
					>
						<Icon name="more" size={19} /><span>{$t('More')}</span>
					</Menu.Trigger>
					<Portal>
						<Menu.Positioner class="z-100">
							<Menu.Content class="min-w-52 border-surface-300-700 p-1 shadow-xl">
								{#each moreItems as [route, label, icon] (label)}
									<Menu.Item
										value={route}
										class="min-w-0 cursor-pointer justify-start gap-2 px-2.5 py-2 text-sm outline-none data-[highlighted]:bg-primary-50-950 data-[highlighted]:text-primary-800-200"
										onclick={() => goto(route)}><Icon name={icon} /> {$t(label)}</Menu.Item
									>
								{/each}
								<Menu.Separator class="my-1 h-px bg-surface-300-700" />
								<div
									class="px-2.5 py-1.5 text-xs font-bold tracking-wide text-surface-600-400 uppercase"
								>
									{$t('Appearance')}
								</div>
								{#each themeOptions as [preference, label, icon] (preference)}
									<Menu.Item
										value={`mobile-theme-${preference}`}
										class="min-w-0 cursor-pointer justify-start gap-2 px-2.5 py-2 text-sm outline-none data-[active=true]:bg-primary-50-950 data-[active=true]:text-primary-800-200 data-[highlighted]:bg-primary-50-950 data-[highlighted]:text-primary-800-200"
										data-active={themePreference === preference}
										onclick={() => onThemeChange(preference)}
									>
										<Icon name={icon} />
										<span class="min-w-0 flex-1">{$t(label)}</span>

										<span class="size-4 shrink-0 text-center" aria-hidden="true">
											{themePreference === preference ? '✓' : ''}
										</span>
									</Menu.Item>
								{/each}
								{#if hasAllowedAction(user?.authorization)}
									<Menu.Item
										value="/admin"
										class="min-w-0 cursor-pointer justify-start gap-2 px-2.5 py-2 text-sm outline-none data-[highlighted]:bg-primary-50-950 data-[highlighted]:text-primary-800-200"
										onclick={() => goto(resolve('admin'))}
										><Icon name="admin" />{$t('Administration')}</Menu.Item
									>
								{/if}
							</Menu.Content>
						</Menu.Positioner>
					</Portal>
				</Menu>
			</Navigation.Menu>
		</nav>
	{/snippet}
</Navigation>
