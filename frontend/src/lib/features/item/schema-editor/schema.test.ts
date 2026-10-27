import { describe, expect, it } from 'vitest';
import { workSchemas, workValidator, isRequiredOnlyUnion } from './schema.js';

describe('editor schema adaptation', () => {
	it('selects a Work and preserves local references without inheriting registry array constraints', () => {
		const registry = {
			$schema: 'https://json-schema.org/draft/2020-12/schema',
			$id: 'https://example.test/registry',
			type: 'array',
			items: { $ref: '#/$defs/work' },
			$defs: {
				work: {
					type: 'object',
					properties: { title: { $ref: '#/$defs/title' } },
					required: ['title']
				},
				title: { type: 'string' }
			}
		};
		const snapshot = structuredClone(registry);
		const { original, rendering } = workSchemas(registry);
		expect(original).not.toHaveProperty('type');
		expect(original).not.toHaveProperty('items');
		expect(rendering.$ref).toBe('#/$defs/work');
		const validate = workValidator(original);
		expect(validate({ title: 'Research' })).toEqual([]);
		expect(validate({ title: 42 }).length).toBeGreaterThan(0);
		expect(validate([]).length).toBeGreaterThan(0);
		expect(registry).toEqual(snapshot);
	});

	it('maps nested validation failures to field paths and user-facing messages', () => {
		const validate = workValidator({
			type: 'object',
			properties: {
				links: {
					type: 'array',
					items: {
						type: 'object',
						properties: { url: { type: 'string', format: 'uri' } }
					}
				}
			}
		});
		expect(validate({ links: [{ url: 'https://example.test' }] })).toEqual([]);
		expect(validate({ links: [{ url: 'relative-id' }] })).toEqual([
			{ path: ['links', 0, 'url'], message: 'Enter a valid absolute URI.' }
		]);
	});

	it('renders required-only alternatives as one object while retaining original validation', () => {
		const schema = {
			type: 'object' as const,
			properties: { name: { type: 'string' as const }, id: { type: 'string' as const } },
			anyOf: [{ required: ['name'] }, { required: ['id'] }]
		};
		expect(isRequiredOnlyUnion(schema)).toBe(true);
		expect(
			isRequiredOnlyUnion({
				type: 'object',
				properties: {},
				anyOf: [{ required: ['name'], properties: {} }]
			})
		).toBe(false);
		const validate = workValidator(schema);
		expect(validate({ name: 'Ada' })).toEqual([]);
		expect(validate({ id: 'local-123' })).toEqual([]);
		expect(validate({})).toContainEqual({
			path: [],
			message: 'Complete at least one of the identifying fields.'
		});
	});
});
