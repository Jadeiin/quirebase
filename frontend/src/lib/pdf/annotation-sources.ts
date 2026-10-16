/** Filters one Annotation list or export request to a displayed source selection. */
export type AnnotationSourceFilters = {
	scope: 'private' | 'project' | undefined;
	project_id: string[] | undefined;
};

export function annotationSourceFilters(
	includePrivate: boolean,
	projectIds: string[]
): AnnotationSourceFilters {
	return {
		scope: !includePrivate ? 'project' : !projectIds.length ? 'private' : undefined,
		project_id: projectIds.length ? projectIds : undefined
	};
}
