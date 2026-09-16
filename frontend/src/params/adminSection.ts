const sections = new Set([
	'users',
	'projects',
	'items',
	'audit',
	'workflows',
	'settings',
	'maintenance'
]);

export function match(
	param: string
): param is 'users' | 'projects' | 'items' | 'audit' | 'workflows' | 'settings' | 'maintenance' {
	return sections.has(param);
}
