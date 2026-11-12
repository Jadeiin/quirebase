import { expect, it } from 'vitest';
import { orcidId } from './orcid.js';

it.each([
	['0000-0002-1825-0097', '0000-0002-1825-0097'],
	[' https://orcid.org/0000-0002-1825-0097/ ', '0000-0002-1825-0097'],
	['HTTP://ORCID.ORG/0000-0002-1694-233x', '0000-0002-1694-233X']
])('normalizes an ORCID filter value %s', (value, expected) => {
	expect(orcidId(value)).toBe(expected);
});

it.each([
	undefined,
	'',
	'0000-0002-1825-0098',
	'0000000218250097',
	'https://orcid.org.example.com/0000-0002-1825-0097',
	'https://orcid.org@elsewhere.example/0000-0002-1825-0097',
	'https://orcid.org/0000-0002-1825-0097?redirect=elsewhere',
	'https://orcid.org/0000-0002-1825-0097#profile',
	'００００-０００２-１８２５-００９７'
])('does not turn invalid input %s into an ORCID', (value) => {
	expect(orcidId(value)).toBeUndefined();
});
