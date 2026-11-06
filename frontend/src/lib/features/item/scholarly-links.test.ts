import { expect, it } from 'vitest';
import { scholarlyLink } from './scholarly-links.js';

it.each([
	['10.1000/research', 'DOI', 'https://doi.org/10.1000/research', 'doi'],
	['10.1000/a?b#c', 'doi', 'https://doi.org/10.1000/a%3Fb%23c', 'doi'],
	['2601.12345v2', 'arXiv', 'https://arxiv.org/abs/2601.12345v2', 'arxiv'],
	['hep-th/9901001', 'arxiv', 'https://arxiv.org/abs/hep-th/9901001', 'arxiv'],
	['W12345', 'OpenAlex', 'https://openalex.org/W12345', 'external-link'],
	['03yrm5c26', 'ROR', 'https://ror.org/03yrm5c26', 'ror'],
	['42', 'PMID', 'https://pubmed.ncbi.nlm.nih.gov/42', 'pubmed'],
	['PMC42', 'PMCID', 'https://pmc.ncbi.nlm.nih.gov/articles/PMC42', 'pubmed']
])('resolves %s in %s without looking up external metadata', (value, namespace, href, icon) => {
	expect(scholarlyLink(value, namespace)).toMatchObject({ href, icon });
});

it.each([
	'https://doi.org/10.1000/research',
	'https://arxiv.org/abs/2601.12345',
	'https://ror.org/03yrm5c26',
	'https://openalex.org/W12345'
])('preserves an existing resolver URL and its visible text: %s', (value) => {
	expect(scholarlyLink(value)).toMatchObject({ label: value, href: value });
});

it.each(['javascript:alert(1)', 'data:text/html,unsafe', 'urn:test:record', 'not a URL'])(
	'keeps unresolvable or unsafe values as plain text: %s',
	(value) => {
		expect(scholarlyLink(value)).toEqual({ label: value });
	}
);

it('does not assign a registry mark to lookalike hosts', () => {
	expect(scholarlyLink('https://doi.org.example.com/10.1000/research').icon).toBe('external-link');
	expect(scholarlyLink('https://orcid.org@elsewhere.example/record').href).toBeUndefined();
});

it('preserves arbitrary local namespace names and omits missing values', () => {
	expect(scholarlyLink('local-42', 'constructor')).toEqual({ label: 'constructor: local-42' });
	expect(scholarlyLink('', 'ROR')).toEqual({ label: '' });
});
