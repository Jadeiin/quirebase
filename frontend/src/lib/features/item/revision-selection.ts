/** Default-all follows successful reads; an explicit choice only keeps surviving revisions. */
export function reconcileRevisionSelection(
	availableIds: readonly string[],
	selectedIds: ReadonlySet<string>,
	explicit: boolean
): string[] {
	return explicit ? availableIds.filter((id) => selectedIds.has(id)) : [...availableIds];
}
