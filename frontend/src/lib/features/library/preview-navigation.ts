export type LibraryPreviewNavigation = {
	position: number | null;
	total: number;
	canPrevious: boolean;
	canNext: boolean;
	busy: boolean;
	error: string;
	previous: () => void;
	next: () => void;
	retry: () => void;
};

type Listing = {
	items: readonly { id: string }[];
	page: number;
	pageSize: number;
	total: number;
};

type Destination = { page: number; itemId: string } | { page: number; edge: 'first' | 'last' };

export type LibraryPreviewPosition = {
	itemId: string;
	index: number;
	itemIds: readonly string[];
};

export function reconcileLibraryPreviewPosition(
	items: readonly { id: string }[],
	itemId: string,
	previous?: LibraryPreviewPosition
): LibraryPreviewPosition | null {
	const itemIds = items.map((item) => item.id);
	const current = itemIds.indexOf(itemId);
	if (current >= 0) return { itemId, index: current, itemIds };
	if (!previous || previous.itemId !== itemId) return null;

	// Remember the gap left by the removed Item, anchored to surviving neighbours.
	// A later refresh may remove more rows after the preview is already absent.
	const oldIndex = previous.itemIds.indexOf(itemId);
	const boundary = oldIndex < 0 ? previous.index : oldIndex;
	for (
		let index = oldIndex < 0 ? boundary : boundary + 1;
		index < previous.itemIds.length;
		index++
	) {
		const successor = itemIds.indexOf(previous.itemIds[index]);
		if (successor >= 0) return { itemId, index: successor, itemIds };
	}
	for (let index = boundary - 1; index >= 0; index--) {
		const predecessor = itemIds.indexOf(previous.itemIds[index]);
		if (predecessor >= 0) return { itemId, index: predecessor + 1, itemIds };
	}
	// All old rows disappeared: following-page replacements start after the gap.
	// An empty snapshot also carries the explicit end position after a page clamp.
	return {
		itemId,
		index: previous.itemIds.length ? 0 : Math.min(previous.index, itemIds.length),
		itemIds
	};
}

// An absent preview uses its reconciled insertion position. A shared preview outside
// the loaded results has no ordering position until the user opens a listed Item.
export function libraryPreviewStep(
	listing: Listing,
	itemId: string,
	direction: -1 | 1,
	previousIndex?: number
): Destination | null {
	const current = listing.items.findIndex((item) => item.id === itemId);
	const index = current < 0 ? previousIndex : current;
	if (index === undefined || index < 0) return null;
	const next = index + (current < 0 && direction === 1 ? 0 : direction);
	if (next >= 0 && next < listing.items.length) {
		return { page: listing.page, itemId: listing.items[next].id };
	}
	if (direction === -1 && listing.page > 1) {
		return { page: listing.page - 1, edge: 'last' };
	}
	if (direction === 1 && listing.page * listing.pageSize < listing.total) {
		return { page: listing.page + 1, edge: 'first' };
	}
	return null;
}
