const sections = new Set(['metadata', 'files', 'organize', 'annotations', 'discussion']);

export function match(
	param: string
): param is 'metadata' | 'files' | 'organize' | 'annotations' | 'discussion' {
	return sections.has(param);
}
