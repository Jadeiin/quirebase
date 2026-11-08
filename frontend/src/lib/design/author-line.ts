export type AuthorLineLayout = { prefixCount: number; lastVisible: boolean; overflowing: boolean };

export function fitAuthorLine(
	widths: readonly number[],
	availableWidth: number,
	separatorWidth: number,
	ellipsisWidth: number,
	maxRows = 1
): AuthorLineLayout {
	if (!widths.length) return { prefixCount: 0, lastVisible: false, overflowing: false };

	// Each complete credit keeps its separator when wrapping. The omission mark follows
	// the same rule, so a retained last author never takes space from the first credit.
	function fits(prefixCount: number, omitted: boolean, last: boolean) {
		let rows = 1;
		let used = 0;
		function place(width: number) {
			if (width > availableWidth) return false;
			if (used + width > availableWidth) {
				rows++;
				used = 0;
			}
			used += width;
			return rows <= maxRows;
		}
		for (let index = 0; index < prefixCount; index++) {
			const separated = index < prefixCount - 1 || omitted || last;
			if (!place(widths[index] + (separated ? separatorWidth : 0))) return false;
		}
		if (omitted && !place(ellipsisWidth + (last ? separatorWidth : 0))) return false;
		return !last || place(widths[widths.length - 1]);
	}

	if (fits(widths.length - 1, false, true)) {
		return { prefixCount: widths.length - 1, lastVisible: true, overflowing: false };
	}
	const lastVisible = widths.length > 1 && fits(1, true, true);
	let prefixCount = 0;
	while (prefixCount < widths.length - 1 && fits(prefixCount + 1, true, lastVisible)) prefixCount++;
	return { prefixCount, lastVisible, overflowing: true };
}
