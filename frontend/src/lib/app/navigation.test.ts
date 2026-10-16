import { describe, expect, it } from 'vitest';
import { isRouteActive } from './navigation';

describe('isRouteActive', () => {
	it('activates a Workspace root only at its Dashboard URL', () => {
		expect(isRouteActive('/workspace/workspace-1', '/workspace/workspace-1', true)).toBe(true);
		expect(isRouteActive('/workspace/workspace-1/projects', '/workspace/workspace-1', true)).toBe(
			false
		);
	});

	it('activates nested routes on segment boundaries', () => {
		expect(
			isRouteActive('/workspace/workspace-1/projects/42', '/workspace/workspace-1/projects')
		).toBe(true);
		expect(
			isRouteActive('/workspace/workspace-1/projector', '/workspace/workspace-1/projects')
		).toBe(false);
	});

	it('keeps the root route exact', () => {
		expect(isRouteActive('/', '/')).toBe(true);
		expect(isRouteActive('/workspace/workspace-1', '/')).toBe(false);
	});
});
