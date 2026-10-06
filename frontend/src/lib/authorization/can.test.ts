import { describe, expect, it } from 'vitest';
import { can, hasAllowedAction } from '#lib/authorization/can.js';

describe('can', () => {
	it('only trusts the server-authored allowed set', () => {
		expect(can({ allowed: ['tag.manage'] }, 'tag.manage')).toBe(true);
		expect(can({ allowed: ['tag.create'] }, 'tag.manage')).toBe(false);
		expect(can(undefined, 'tag.create')).toBe(false);
	});
	it('detects a surface from concrete server-authored actions', () => {
		expect(hasAllowedAction({ allowed: ['workspace.read'] })).toBe(true);
		expect(hasAllowedAction({ allowed: [] })).toBe(false);
		expect(hasAllowedAction(undefined)).toBe(false);
	});
});
