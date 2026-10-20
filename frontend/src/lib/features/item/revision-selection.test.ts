import { describe, expect, it } from 'vitest';
import { reconcileRevisionSelection } from './revision-selection.js';

describe('document revision selection', () => {
	it('follows replaced and newly uploaded revisions while using default-all', () => {
		expect(reconcileRevisionSelection(['new-pdf'], new Set(['deleted-pdf']), false)).toEqual([
			'new-pdf'
		]);
		expect(reconcileRevisionSelection([], new Set(['deleted-pdf']), false)).toEqual([]);
	});

	it('preserves an explicit subset without selecting new uploads or retaining deleted IDs', () => {
		expect(
			reconcileRevisionSelection(
				['kept-pdf', 'excluded-pdf', 'new-pdf'],
				new Set(['deleted-pdf', 'kept-pdf']),
				true
			)
		).toEqual(['kept-pdf']);
		expect(reconcileRevisionSelection(['new-pdf'], new Set(['deleted-pdf']), true)).toEqual([]);
	});

	it('preserves an intentional empty selection', () => {
		expect(reconcileRevisionSelection(['pdf'], new Set(), true)).toEqual([]);
	});
});
