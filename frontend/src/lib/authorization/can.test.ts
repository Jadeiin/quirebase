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

	it('keeps variant grants independent of the base action grant', () => {
		const decisions = {
			allowed: [],
			variants: { 'project.create': ['open', 'workspace'] }
		} satisfies AuthorizationDecisionSet;

		expect(can(decisions, 'project.create')).toBe(false);
		expect(canVariant(decisions, 'project.create', 'open')).toBe(true);
		expect(canVariant(decisions, 'project.create', 'managed')).toBe(false);
	});

	it('rejects variants without an explicit relation projection', () => {
		expect(canVariant({ allowed: ['project.create'] }, 'project.create', 'open')).toBe(false);
		expect(
			canVariant({ allowed: ['project.create'], variants: {} }, 'project.create', 'open')
		).toBe(false);
		expect(canVariant(undefined, 'project.create', 'open')).toBe(false);
	});

	it('preserves metadata update grants alongside participation restrictions', () => {
		const decisions = {
			allowed: ['project.update'],
			variants: { 'project.update': ['workspace', 'open'] }
		} satisfies AuthorizationDecisionSet;
		expect(can(decisions, 'project.update')).toBe(true);
		expect(canVariant(decisions, 'project.update', 'managed')).toBe(false);
	});

	it('detects a surface from concrete server-authored actions', () => {
		expect(hasAllowedAction({ allowed: ['workspace.read'] })).toBe(true);
		expect(hasAllowedAction({ allowed: [] })).toBe(false);
		expect(hasAllowedAction({ allowed: [], variants: { 'project.create': ['open'] } })).toBe(true);
		expect(hasAllowedAction({ allowed: [], variants: { 'project.create': [] } })).toBe(false);
		expect(hasAllowedAction(undefined)).toBe(false);
	});
});
