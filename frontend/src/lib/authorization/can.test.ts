import { describe, expect, it } from 'vitest';
import { can, hasAllowedAction } from '$lib/authorization/can';

describe('can', () => {
	it('only trusts the server-authored allowed set', () => {
		expect(can({ allowed: ['tag.manage'] }, 'tag', 'manage')).toBe(true);
		expect(can({ allowed: ['tag.read'] }, 'tag', 'manage')).toBe(false);
		expect(can(undefined, 'tag', 'read')).toBe(false);
	});

	it('checks relation constraints without changing the resource-action key', () => {
		const decisions = {
			allowed: ['project.create'],
			relations: { 'project.create': ['open', 'workspace'] }
		};

		expect(can(decisions, 'project', 'create')).toBe(true);
		expect(can(decisions, 'project', 'create', 'open')).toBe(true);
		expect(can(decisions, 'project', 'create', 'managed')).toBe(false);
	});

	it('detects a surface from concrete server-authored actions', () => {
		expect(hasAllowedAction({ allowed: ['audit.read'] })).toBe(true);
		expect(hasAllowedAction({ allowed: [] })).toBe(false);
		expect(hasAllowedAction(undefined)).toBe(false);
	});
});
