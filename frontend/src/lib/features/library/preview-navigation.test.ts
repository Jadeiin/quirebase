import { describe, expect, it } from 'vitest';
import { libraryPreviewStep, reconcileLibraryPreviewPosition } from './preview-navigation.js';

const listing = {
	items: ['a', 'b', 'c'].map((id) => ({ id })),
	page: 2,
	pageSize: 3,
	total: 8
};

describe('continuous Library preview', () => {
	it('uses the loaded server order and moves across page boundaries', () => {
		expect(libraryPreviewStep(listing, 'b', -1)).toEqual({ page: 2, itemId: 'a' });
		expect(libraryPreviewStep(listing, 'b', 1)).toEqual({ page: 2, itemId: 'c' });
		expect(libraryPreviewStep(listing, 'a', -1)).toEqual({ page: 1, edge: 'last' });
		expect(libraryPreviewStep(listing, 'c', 1)).toEqual({ page: 3, edge: 'first' });
	});

	it('stops at the first and last result, including a partial final page', () => {
		expect(libraryPreviewStep({ ...listing, page: 1 }, 'a', -1)).toBeNull();
		expect(
			libraryPreviewStep({ ...listing, page: 3, items: [{ id: 'last' }] }, 'last', 1)
		).toBeNull();
	});

	it('does not invent a position for deep-linked Items outside the current results', () => {
		expect(libraryPreviewStep(listing, 'outside', -1)).toBeNull();
		expect(libraryPreviewStep(listing, 'outside', 1)).toBeNull();
	});

	it('continues with the successor when organizing removes the current result', () => {
		const refreshed = { ...listing, items: [{ id: 'a' }, { id: 'c' }] };
		expect(libraryPreviewStep(refreshed, 'b', 1, 1)).toEqual({ page: 2, itemId: 'c' });
		expect(libraryPreviewStep(refreshed, 'b', -1, 1)).toEqual({ page: 2, itemId: 'a' });
		expect(libraryPreviewStep({ ...refreshed, total: 5 }, 'b', 1, 2)).toBeNull();
	});

	it('can return to a surviving result after bulk removal also removes earlier rows', () => {
		const refreshed = { ...listing, page: 1, items: [{ id: 'b' }], total: 1 };
		const previous = reconcileLibraryPreviewPosition(listing.items, 'c')!;
		const position = reconcileLibraryPreviewPosition(refreshed.items, 'c', previous)!;
		expect(libraryPreviewStep(refreshed, 'c', -1, position.index)).toEqual({
			page: 1,
			itemId: 'b'
		});
		expect(libraryPreviewStep(refreshed, 'c', 1, position.index)).toBeNull();
	});

	it('keeps both surviving neighbours on the current page after bulk removal', () => {
		const items = ['a', 'b', 'c', 'd', 'e', 'f'].map((id) => ({ id }));
		const refreshed = {
			items: ['b', 'd', 'f'].map((id) => ({ id })),
			page: 2,
			pageSize: 6,
			total: 9
		};
		const previous = reconcileLibraryPreviewPosition(items, 'e')!;
		const position = reconcileLibraryPreviewPosition(refreshed.items, 'e', previous)!;
		expect(libraryPreviewStep(refreshed, 'e', -1, position.index)).toEqual({
			page: 2,
			itemId: 'd'
		});
		expect(libraryPreviewStep(refreshed, 'e', 1, position.index)).toEqual({ page: 2, itemId: 'f' });
	});

	it('reconciles the same gap across further removals and following-page replacements', () => {
		const items = ['a', 'b', 'c', 'd'].map((id) => ({ id }));
		const original = reconcileLibraryPreviewPosition(items, 'b')!;
		const removed = reconcileLibraryPreviewPosition(
			[{ id: 'a' }, { id: 'c' }, { id: 'd' }],
			'b',
			original
		)!;
		const refreshed = { ...listing, items: [{ id: 'c' }, { id: 'd' }, { id: 'e' }] };
		const position = reconcileLibraryPreviewPosition(refreshed.items, 'b', removed)!;
		expect(libraryPreviewStep(refreshed, 'b', 1, position.index)).toEqual({ page: 2, itemId: 'c' });
		expect(libraryPreviewStep(refreshed, 'b', -1, position.index)).toEqual({
			page: 1,
			edge: 'last'
		});
	});

	it('continues at the first replacement if all previously loaded rows disappear', () => {
		const previous = reconcileLibraryPreviewPosition(listing.items, 'b')!;
		const refreshed = { ...listing, items: [{ id: 'd' }, { id: 'e' }] };
		const position = reconcileLibraryPreviewPosition(refreshed.items, 'b', previous)!;
		expect(libraryPreviewStep(refreshed, 'b', 1, position.index)).toEqual({ page: 2, itemId: 'd' });
		const empty = reconcileLibraryPreviewPosition([], 'b', previous)!;
		const restored = reconcileLibraryPreviewPosition(refreshed.items, 'b', empty)!;
		expect(libraryPreviewStep(refreshed, 'b', 1, restored.index)).toEqual({ page: 2, itemId: 'd' });
	});

	it('keeps an explicit end position when removal clamps the last page', () => {
		const refreshed = { ...listing, page: 1, total: 3 };
		const position = reconcileLibraryPreviewPosition(refreshed.items, 'removed', {
			itemId: 'removed',
			index: 3,
			itemIds: []
		})!;
		expect(libraryPreviewStep(refreshed, 'removed', -1, position.index)).toEqual({
			page: 1,
			itemId: 'c'
		});
		expect(libraryPreviewStep(refreshed, 'removed', 1, position.index)).toBeNull();
	});

	it('does not borrow another preview position or invent one for an unknown Item', () => {
		const previous = reconcileLibraryPreviewPosition(listing.items, 'b')!;
		expect(reconcileLibraryPreviewPosition(listing.items, 'outside')).toBeNull();
		expect(reconcileLibraryPreviewPosition(listing.items, 'outside', previous)).toBeNull();
	});

	it('uses the authoritative index if a removed preview reappears', () => {
		const previous = reconcileLibraryPreviewPosition(listing.items, 'b')!;
		const removed = reconcileLibraryPreviewPosition([{ id: 'c' }], 'b', previous)!;
		const position = reconcileLibraryPreviewPosition([{ id: 'b' }, { id: 'c' }], 'b', removed)!;
		expect(position.index).toBe(0);
	});
});
