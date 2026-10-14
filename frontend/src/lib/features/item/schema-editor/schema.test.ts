import { execFileSync } from 'node:child_process';
import { describe, expect, it } from 'vitest';
import { workSchemas, workValidator, isRequiredOnlyUnion } from './schema.js';

const registry = JSON.parse(
	execFileSync(
		'uv',
		[
			'run',
			'--offline',
			'python',
			'-c',
			'from commonmeta_schema import schema_path; print(schema_path("1.0").read_text())'
		],
		{ encoding: 'utf8' }
	)
);
const work = {
	id: 'urn:uuid:00000000-0000-4000-8000-000000000001',
	type: 'Dataset',
	title: 'Research',
	contributors: [
		{
			type: 'Person',
			person: { name: 'Ada', affiliations: [{ name: 'University' }] },
			roles: ['Author']
		}
	],
	identifiers: [
		{ identifier_type: 'DOI', identifier: '10.1000/a' },
		{ identifier_type: 'DOI', identifier: '10.1000/b' }
	],
	funding_references: [{ funder_name: 'Foundation', award_number: '123' }]
};

describe('official Work editor schema', () => {
	it('selects a Work without inheriting the registry array constraints', () => {
		const { original, rendering } = workSchemas(registry);
		expect(original).not.toHaveProperty('type');
		expect(original).not.toHaveProperty('items');
		expect(rendering.$ref).toBe('#/$defs/work');
		expect(workValidator(original)(work)).toEqual([]);
		expect(registry.type).toBe('array');
	});
	it('validates against the original standard, preserving partial dates and full timestamps', () => {
		const validate = workValidator(workSchemas(registry).original);
		for (const date of ['2024', '2024-02', '2024-02-29', '2024-02-29T12:34:56+08:00'])
			expect(validate({ ...work, date_published: date })).toEqual([]);
		expect(validate({ ...work, id: 'relative-id' }).some((error) => error.path[0] === 'id')).toBe(
			true
		);
		expect(validate({ ...work, contributors: [] }).length).toBeGreaterThan(0);
		expect(validate({ ...work, extra: true }).length).toBeGreaterThan(0);
	});
	it('resolves required-only alternatives as one object without weakening validation', () => {
		expect(
			isRequiredOnlyUnion({
				type: 'object',
				properties: { name: { type: 'string' }, id: { type: 'string' } },
				anyOf: [{ required: ['name'] }, { required: ['id'] }]
			})
		).toBe(true);
		expect(
			isRequiredOnlyUnion({
				type: 'object',
				properties: {},
				anyOf: [{ required: ['name'], properties: {} }]
			})
		).toBe(false);
		const validate = workValidator(workSchemas(registry).original);
		expect(validate({ ...work, funding_references: [{}] }).length).toBeGreaterThan(0);
	});
});
