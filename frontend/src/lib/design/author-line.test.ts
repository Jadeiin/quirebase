import { describe, expect, it } from 'vitest';
import { fitAuthorLine } from './author-line.js';

describe('whole author names in a single line', () => {
	it('shows every name when the full line fits, including the exact boundary', () => {
		const expected = { prefixCount: 2, lastVisible: true, overflowing: false };
		expect(fitAuthorLine([10, 20, 30], 100, 5, 10)).toEqual(expected);
		expect(fitAuthorLine([10, 20, 30], 70, 5, 10)).toEqual(expected);
	});

	it('preserves the complete last credit before filling the preceding names', () => {
		expect(fitAuthorLine([20, 20, 20, 30], 75, 5, 10)).toEqual({
			prefixCount: 1,
			lastVisible: true,
			overflowing: true
		});
	});

	it('keeps the first credit when the first and last names cannot both fit', () => {
		expect(fitAuthorLine([20, 20, 30], 45, 5, 10)).toEqual({
			prefixCount: 1,
			lastVisible: false,
			overflowing: true
		});
		expect(fitAuthorLine([20, 20, 30], 69, 5, 10)).toEqual({
			prefixCount: 2,
			lastVisible: false,
			overflowing: true
		});
		expect(fitAuthorLine([20, 20, 30], 70, 5, 10)).toEqual({
			prefixCount: 1,
			lastVisible: true,
			overflowing: true
		});
	});

	it('hides an overlong last credit completely and uses the remaining space for a prefix', () => {
		expect(fitAuthorLine([20, 20, 100], 60, 5, 10)).toEqual({
			prefixCount: 2,
			lastVisible: false,
			overflowing: true
		});
	});

	it('does not skip an overlong preceding name to reveal a later short name', () => {
		expect(fitAuthorLine([100, 10, 20], 70, 5, 10)).toEqual({
			prefixCount: 0,
			lastVisible: false,
			overflowing: true
		});
		expect(fitAuthorLine([20, 100, 10, 20], 90, 5, 10)).toEqual({
			prefixCount: 1,
			lastVisible: true,
			overflowing: true
		});
	});

	it('keeps a single name whole or replaces it with the omission marker', () => {
		expect(fitAuthorLine([20], 20, 5, 10)).toEqual({
			prefixCount: 0,
			lastVisible: true,
			overflowing: false
		});
		expect(fitAuthorLine([20], 19, 5, 10)).toEqual({
			prefixCount: 0,
			lastVisible: false,
			overflowing: true
		});
	});

	it('does not expose a partial name when no complete name can fit', () => {
		expect(fitAuthorLine([20, 30], 14, 5, 10)).toEqual({
			prefixCount: 0,
			lastVisible: false,
			overflowing: true
		});
		expect(fitAuthorLine([20, 30], 0, 5, 10)).toEqual({
			prefixCount: 0,
			lastVisible: false,
			overflowing: true
		});
	});

	it('retains fractional widths rather than rounding a name into the available space', () => {
		expect(fitAuthorLine([10.25, 10.25, 20.25], 44, 2.5, 8.5)).toEqual({
			prefixCount: 1,
			lastVisible: true,
			overflowing: true
		});
	});

	it('renders no names or omission marker for an empty author list', () => {
		expect(fitAuthorLine([], 100, 5, 10)).toEqual({
			prefixCount: 0,
			lastVisible: false,
			overflowing: false
		});
	});
});
