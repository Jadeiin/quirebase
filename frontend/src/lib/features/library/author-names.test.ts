import { expect, it } from 'vitest';
import { authorFilterLabel } from './author-names.js';

it.each([
	{ last_name: 'Wang', first_name: 'Wei', full_name: 'Wang Wei' },
	{ last_name: '王', first_name: '伟', full_name: '王伟' },
	{
		last_name: 'Research, Development & 方法',
		first_name: null,
		full_name: 'Research, Development & 方法'
	},
	{ last_name: 'Ada', first_name: null, full_name: 'Ada' }
])('uses the unambiguous record credit for the exact filter %j', (author) => {
	expect(authorFilterLabel(author.last_name, author.first_name ?? '', [author, author])).toBe(
		author.full_name
	);
});

it('uses reading-order parts when matching credits disagree, without changing the exact keys', () => {
	const authors = [
		{ last_name: ' Wang ', first_name: ' Wei ', full_name: 'Wang Wei' },
		{ last_name: ' Wang ', first_name: ' Wei ', full_name: 'Wei Wang' }
	];
	const snapshot = structuredClone(authors);
	expect(authorFilterLabel(' Wang ', ' Wei ', authors)).toBe('Wei Wang');
	expect(authors).toEqual(snapshot);
});

it('does not infer a full credit for a family-only criterion or normalize exact matching values', () => {
	const author = { last_name: 'Wang', first_name: 'Wei', full_name: 'Wang Wei' };
	expect(authorFilterLabel('Wang', undefined, [author])).toBe('Wang');
	expect(authorFilterLabel(' Wang ', 'Wei', [author])).toBe('Wei Wang');
	expect(authorFilterLabel('Wang', ' Wei ', [author])).toBe('Wei Wang');
	expect(authorFilterLabel('Wang', '', [author])).toBe('Wang');
});

it('falls back to available parts for deep links and unloaded results', () => {
	expect(authorFilterLabel('Lovelace', 'Ada')).toBe('Ada Lovelace');
	expect(authorFilterLabel('Research Council', '')).toBe('Research Council');
	expect(authorFilterLabel('Ada', '')).toBe('Ada');
	expect(authorFilterLabel('Lovelace', '  ')).toBe('Lovelace');
});
