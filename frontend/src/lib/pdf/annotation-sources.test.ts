import { describe, expect, it } from 'vitest';
import { annotationSourceFilters } from '#lib/pdf/annotation-sources.js';

describe('annotationSourceFilters', () => {
	it('selects private annotations alone when no Project is displayed', () => {
		expect(annotationSourceFilters(true, [])).toEqual({ scope: 'private', project_id: undefined });
	});

	it('adds displayed Projects to private annotations', () => {
		expect(annotationSourceFilters(true, ['project-1', 'project-2'])).toEqual({
			scope: undefined,
			project_id: ['project-1', 'project-2']
		});
	});

	it('selects only displayed Projects when private annotations are hidden', () => {
		expect(annotationSourceFilters(false, ['project-1'])).toEqual({
			scope: 'project',
			project_id: ['project-1']
		});
	});
});
