<script lang="ts">
	import { Popover, Portal } from '@skeletonlabs/skeleton-svelte';
	import Icon from '$lib/design/Icon.svelte';
	import PopoverCloseButton from '$lib/design/PopoverCloseButton.svelte';
	import PopoverTriggerButton from '$lib/design/PopoverTriggerButton.svelte';
	import { getWorkflowCenter } from '$lib/features/workflows/center.svelte';
	import WorkflowJobRow from '$lib/features/workflows/WorkflowJobRow.svelte';
	import { t } from '$lib/i18n';

	const center = getWorkflowCenter();
	let panelOpen = $state(false);
	const activeCount = $derived(center.jobs.filter((job) => !job.outcome).length);
	const badgeCount = $derived(activeCount > 0 ? activeCount : center.jobs.length);
</script>

{#if center.jobs.length > 0}
	{#each center.jobs as job (job.id)}
		<WorkflowJobRow {job} visible={false} />
	{/each}
	<div class="fixed right-4 bottom-20 z-80 md:right-6 md:bottom-6">
		<Popover
			open={panelOpen}
			onOpenChange={(details) => (panelOpen = details.open)}
			positioning={{ placement: 'top-end', gutter: 12 }}
		>
			<PopoverTriggerButton
				variant="filled"
				class="h-12 rounded-full pr-5 pl-4 shadow-xl"
				aria-label={`${$t('Background tasks')} (${badgeCount})`}
			>
				<Icon name="rotate" size={20} />
				<span class="min-w-6 text-center text-sm tabular-nums" aria-hidden="true">{badgeCount}</span
				>
			</PopoverTriggerButton>
			<Portal>
				<Popover.Positioner class="z-80">
					<Popover.Content
						class="w-80 max-w-[calc(100vw-2rem)] overflow-hidden rounded-container border border-surface-300-700 bg-surface-50-950 shadow-2xl"
					>
						<header
							class="flex items-center justify-between border-b border-surface-300-700 px-4 py-3"
						>
							<Popover.Title class="text-sm font-bold">{$t('Background tasks')}</Popover.Title>
							<PopoverCloseButton />
						</header>
						<div class="max-h-80 divide-y divide-surface-300-700 overflow-auto">
							{#each center.jobs as job (job.id)}
								<WorkflowJobRow {job} visible={true} />
							{/each}
						</div>
					</Popover.Content>
				</Popover.Positioner>
			</Portal>
		</Popover>
	</div>
{/if}
