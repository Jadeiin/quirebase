<script lang="ts">
	import type { HTMLInputAttributes } from 'svelte/elements';
	import { onMount } from 'svelte';
	import { DatePicker, Portal, parseDate, type DateValue } from '@skeletonlabs/skeleton-svelte';
	import Icon from '#lib/design/Icon.svelte';
	import { activeLocale, t } from '#lib/i18n.js';

	let {
		value = $bindable(''),
		precision = 'day',
		label,
		min = '0001-01-01',
		max = '9999-12-31',
		inputAttributes = {}
	} = $props<{
		value?: string;
		precision?: 'year' | 'month' | 'day';
		label: string;
		min?: string;
		max?: string;
		inputAttributes?: HTMLInputAttributes;
	}>();
	let input = $state<HTMLInputElement>();
	let portalTarget = $state<HTMLElement>();
	onMount(() => {
		portalTarget = input?.closest<HTMLElement>('[role="dialog"]') ?? undefined;
	});
	const minDate = $derived(parseDate(min));
	const maxDate = $derived(parseDate(max));

	const length = $derived(precision === 'day' ? 10 : precision === 'month' ? 7 : 4);
	const placeholder = $derived(
		precision === 'day' ? 'YYYY-MM-DD' : precision === 'month' ? 'YYYY-MM' : 'YYYY'
	);
	const pattern = $derived(
		precision === 'day'
			? '[0-9]{4}-[0-9]{2}-[0-9]{2}'
			: precision === 'month'
				? '[0-9]{4}-[0-9]{2}'
				: '[0-9]{4}'
	);
	let dates = $state<DateValue[]>([]);
	$effect(() => {
		const date = parseInput(value);
		// Keep an invalid draft visible; Zag would clear the input if its value became empty.
		if (date) dates = [date];
		else if (!value) dates = [];
	});

	function parseInput(input: string): DateValue | undefined {
		if (!new RegExp(`^${pattern}$`).test(input)) return;
		try {
			// Calendar anchors are internal: persist only the precision the user supplied.
			const date = parseDate(
				precision === 'year' ? `${input}-01-01` : precision === 'month' ? `${input}-01` : input
			);
			return date.compare(minDate) >= 0 && date.compare(maxDate) <= 0 ? date : undefined;
		} catch {
			return undefined;
		}
	}

	$effect(() => {
		input?.setCustomValidity(
			value && !parseInput(value) ? $t('Enter a valid {format} date.', { format: placeholder }) : ''
		);
	});
</script>

{#key precision}
	<DatePicker
		locale={$activeLocale}
		value={dates}
		defaultFocusedValue={parseInput(value)}
		minView={precision}
		defaultView={precision}
		min={minDate}
		max={maxDate}
		format={(date) => date.toString().slice(0, length)}
		parse={parseInput}
		onValueChange={(details) => (value = details.value[0]?.toString().slice(0, length) ?? '')}
		positioning={{ placement: 'bottom-start', strategy: 'fixed' }}
	>
		<DatePicker.Label>{label}</DatePicker.Label>
		<DatePicker.Control>
			<DatePicker.Context>
				{#snippet children(calendar)}
					<DatePicker.Input {placeholder} {pattern} class="pr-10" fixOnBlur={false}>
						{#snippet element(attributes)}
							<!-- Zag filters separators by locale even with custom format/parse. The product input is ISO. -->
							<input
								{...attributes}
								{...inputAttributes}
								bind:this={input}
								{value}
								onbeforeinput={undefined}
								oninput={(event) => {
									value = event.currentTarget.value;
									const date = parseInput(value);
									if (date) calendar().setFocusedValue(date);
								}}
								onkeydowncapture={(event) => {
									if (event.key === 'Enter' && value && !parseInput(value)) {
										event.preventDefault();
										event.stopPropagation();
										input?.reportValidity();
									}
								}}
							/>
						{/snippet}
					</DatePicker.Input>
				{/snippet}
			</DatePicker.Context>
			<DatePicker.Trigger aria-label={$t('Choose date for {label}', { label })}
				><Icon name="calendar" size={16} /></DatePicker.Trigger
			>
		</DatePicker.Control>
		<Portal target={portalTarget}>
			<DatePicker.Positioner class="z-100">
				<DatePicker.Content aria-label={$t('Calendar for {label}', { label })} class="shadow-xl">
					<DatePicker.Context>
						{#snippet children(calendar)}
							{#if precision === 'day'}
								<DatePicker.View view="day">
									{@render viewControl()}
									<DatePicker.Table>
										<DatePicker.TableHead
											><DatePicker.TableRow>
												{#each calendar().weekDays as day (day.short)}<DatePicker.TableHeader
														>{day.short}</DatePicker.TableHeader
													>{/each}
											</DatePicker.TableRow></DatePicker.TableHead
										>
										<DatePicker.TableBody>
											{#each calendar().weeks as week (week[0].toString())}<DatePicker.TableRow>
													{#each week as day (day.toString())}<DatePicker.TableCell value={day}
															><DatePicker.TableCellTrigger>{day.day}</DatePicker.TableCellTrigger
															></DatePicker.TableCell
														>{/each}
												</DatePicker.TableRow>{/each}
										</DatePicker.TableBody>
									</DatePicker.Table>
								</DatePicker.View>
							{/if}
							{#if precision !== 'year'}
								<DatePicker.View view="month">
									{@render viewControl()}
									<DatePicker.Table
										><DatePicker.TableBody>
											{#each calendar().getMonthsGrid( { columns: 3 } ) as months (months[0].value)}<DatePicker.TableRow
												>
													{#each months as month (month.value)}<DatePicker.TableCell
															value={month.value}
															><DatePicker.TableCellTrigger class="min-w-16"
																>{month.label}</DatePicker.TableCellTrigger
															></DatePicker.TableCell
														>{/each}
												</DatePicker.TableRow>{/each}
										</DatePicker.TableBody></DatePicker.Table
									>
								</DatePicker.View>
							{/if}
							<DatePicker.View view="year">
								{@render viewControl()}
								<DatePicker.Table
									><DatePicker.TableBody>
										{#each calendar().getYearsGrid( { columns: 3 } ) as years (years[0].value)}<DatePicker.TableRow
											>
												{#each years as year (year.value)}<DatePicker.TableCell value={year.value}
														><DatePicker.TableCellTrigger class="min-w-16"
															>{year.label}</DatePicker.TableCellTrigger
														></DatePicker.TableCell
													>{/each}
											</DatePicker.TableRow>{/each}
									</DatePicker.TableBody></DatePicker.Table
								>
							</DatePicker.View>
						{/snippet}
					</DatePicker.Context>
				</DatePicker.Content>
			</DatePicker.Positioner>
		</Portal>
	</DatePicker>
{/key}

{#snippet viewControl()}
	<DatePicker.ViewControl>
		<DatePicker.PrevTrigger aria-label={$t('Previous calendar period')}
			><Icon name="chevron-left" size={16} /></DatePicker.PrevTrigger
		>
		<DatePicker.ViewTrigger><DatePicker.RangeText /></DatePicker.ViewTrigger>
		<DatePicker.NextTrigger aria-label={$t('Next calendar period')}
			><Icon name="chevron-right" size={16} /></DatePicker.NextTrigger
		>
	</DatePicker.ViewControl>
{/snippet}
