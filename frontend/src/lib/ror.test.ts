import { expect, it } from 'vitest';
import { rorId } from './ror.js';

it.each(['03yrm5c26', ' https://ror.org/03yrm5c26/ ', 'HTTP://ROR.ORG/03YRM5C26'])(
	'normalizes ROR %s and verifies its checksum',
	(value) => {
		expect(rorId(value)).toBe('03yrm5c26');
	}
);

it.each([
	undefined,
	'',
	'03yrm5c27',
	'13yrm5c26',
	'03orm5c26',
	'03yrm5c2x',
	'https://ror.org.example.com/03yrm5c26',
	'https://ror.org@elsewhere.example/03yrm5c26',
	'https://ror.org/03yrm5c26?redirect=elsewhere',
	'https://ror.org/03yrm5c26#profile'
])('does not turn invalid input %s into a ROR filter', (value) => {
	expect(rorId(value)).toBeUndefined();
});
