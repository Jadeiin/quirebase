export function fitAuthorLine(
	widths: readonly number[],
	availableWidth: number,
	separatorWidth: number,
	ellipsisWidth: number
): { prefixCount: number; lastVisible: boolean; overflowing: boolean } {
	if (!widths.length) return { prefixCount: 0, lastVisible: false, overflowing: false };

	const fullWidth =
		widths.reduce((total, width) => total + width, 0) + (widths.length - 1) * separatorWidth;
	if (fullWidth <= availableWidth) {
		return { prefixCount: widths.length - 1, lastVisible: true, overflowing: false };
	}

	const lastWidth = widths[widths.length - 1];
	const lastVisible =
		widths.length > 1 &&
		widths[0] + lastWidth + 2 * separatorWidth + ellipsisWidth <= availableWidth;
	let usedWidth = ellipsisWidth + (lastVisible ? separatorWidth + lastWidth : 0);
	let prefixCount = 0;
	while (prefixCount < widths.length - 1) {
		const nextWidth = widths[prefixCount] + separatorWidth;
		if (usedWidth + nextWidth > availableWidth) break;
		usedWidth += nextWidth;
		prefixCount++;
	}
	return { prefixCount, lastVisible, overflowing: true };
}
