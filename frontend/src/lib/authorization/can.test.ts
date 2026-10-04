import { describe, expect, it } from 'vitest';
import {
	can,
	canVariant,
	hasAllowedAction,
	type AuthorizationDecisionSet
} from '#lib/authorization/can.js';

describe('can', () => {
	it('only trusts the server-authored allowed set', () => {
		expect(can({ allowed: ['tag.manage'] }, 'tag.manage')).toBe(true);
		expect(can({ allowed: ['tag.create'] }, 'tag.manage')).toBe(false);
		expect(can(undefined, 'tag.create')).toBe(false);
	});

	it('checks relation constraints without changing the resource-action key', () => {
		const decisions = {
			allowed: ['project.create'],
			relations: { 'project.create': ['open', 'workspace'] }
		} satisfies AuthorizationDecisionSet;

		expect(can(decisions, 'project.create')).toBe(true);
		expect(canVariant(decisions, 'project.create', 'open')).toBe(true);
		expect(canVariant(decisions, 'project.create', 'managed')).toBe(false);
	});

	it('rejects variants without an explicit grant and relation projection', () => {
		expect(canVariant({ allowed: ['project.create'] }, 'project.create', 'open')).toBe(false);
		expect(
			canVariant({ allowed: ['project.create'], relations: {} }, 'project.create', 'open')
		).toBe(false);
		expect(
			canVariant(
				{ allowed: [], relations: { 'project.create': ['open'] } },
				'project.create',
				'open'
			)
		).toBe(false);
		expect(canVariant(undefined, 'project.create', 'open')).toBe(false);
	});

	it('detects a surface from concrete server-authored actions', () => {
		expect(hasAllowedAction({ allowed: ['workspace.read'] })).toBe(true);
		expect(hasAllowedAction({ allowed: [] })).toBe(false);
		expect(hasAllowedAction(undefined)).toBe(false);
	});
});
