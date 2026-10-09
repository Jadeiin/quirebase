const storageKey = 'quirebase:default-workspace';

export function defaultWorkspacePreference(): string | null {
	if (typeof localStorage === 'undefined') return null;
	return localStorage.getItem(storageKey);
}

export function setDefaultWorkspacePreference(workspaceId: string): void {
	if (typeof localStorage !== 'undefined') localStorage.setItem(storageKey, workspaceId);
}

export function clearDefaultWorkspacePreference(): void {
	if (typeof localStorage !== 'undefined') localStorage.removeItem(storageKey);
}
