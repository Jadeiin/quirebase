import { getContext, setContext } from 'svelte';
import { SvelteMap, SvelteSet } from 'svelte/reactivity';
import type { Config } from '@sjsf/form';

const contextKey = Symbol('metadata-field-visibility');
type Path = readonly (string | number)[];
const pathKey = (path: Path) => JSON.stringify(path);

export function hasFieldValue(value: unknown): boolean {
	if (value === undefined || value === null || value === '') return false;
	if (Array.isArray(value)) return value.some(hasFieldValue);
	if (typeof value === 'object') return Object.values(value).some(hasFieldValue);
	return true;
}

// These are presentation choices; the official schema still owns fields and validation.
function isCommonField(path: Path): boolean {
	const name = String(path.at(-1));
	if (path.length === 1)
		return [
			'title',
			'type',
			'date_published',
			'container',
			'contributors',
			'identifiers',
			'funding_references',
			'subjects'
		].includes(name);
	if (['name', 'funder_name'].includes(name)) return true;
	if (path.at(-2) === 'person' && ['given_name', 'family_name'].includes(name)) return true;
	if (path[0] === 'contributors' && path.length === 3 && name === 'roles') return true;
	return path.length === 2 && path[0] === 'container' && ['title', 'type'].includes(name);
}

export function createFieldVisibility() {
	let showAll = $state(false);
	const revealed = new SvelteSet<string>();
	const expansions = new SvelteMap<string, number>();
	let sequence = 0;
	const state = {
		get showAll() {
			return showAll;
		},
		set showAll(value: boolean) {
			showAll = value;
		},
		isOptional(config: Config) {
			return !config.required && !isCommonField(config.path);
		},
		isVisible(config: Config, value: unknown) {
			return (
				!state.isOptional(config) ||
				showAll ||
				hasFieldValue(value) ||
				revealed.has(pathKey(config.path))
			);
		},
		remember(path: Path, value: unknown) {
			// Clearing a field must not remove the focused control while typing.
			if (hasFieldValue(value)) revealed.add(pathKey(path));
		},
		expansion(path: Path) {
			return expansions.get(pathKey(path)) ?? 0;
		},
		reveal(path: Path) {
			const request = ++sequence;
			for (let length = 1; length <= path.length; length++) {
				const key = pathKey(path.slice(0, length));
				revealed.add(key);
				expansions.set(key, request);
			}
		},
		reindex(arrayPath: Path, index: (previous: number) => number | null) {
			function nextKey(key: string): string | null {
				const path: (string | number)[] = JSON.parse(key);
				const previous = path[arrayPath.length];
				if (
					typeof previous !== 'number' ||
					!arrayPath.every((part, position) => path[position] === part)
				)
					return key;
				const next = index(previous);
				if (next === null) return null;
				if (next === previous) return key;
				path[arrayPath.length] = next;
				return pathKey(path);
			}
			const fields = [...revealed]
				.map((key) => ({ key, next: nextKey(key) }))
				.filter(({ key, next }) => key !== next);
			const sections = [...expansions]
				.map(([key, request]) => ({ key, request, next: nextKey(key) }))
				.filter(({ key, next }) => key !== next);
			// Remove all old keys before inserting: moves can exchange two occupied paths.
			for (const { key } of fields) revealed.delete(key);
			for (const { key } of sections) expansions.delete(key);
			for (const { next } of fields) if (next !== null) revealed.add(next);
			for (const { next, request } of sections) if (next !== null) expansions.set(next, request);
		},
		reset() {
			revealed.clear();
			expansions.clear();
		}
	};
	setContext(contextKey, state);
	return state;
}

export function getFieldVisibility(): ReturnType<typeof createFieldVisibility> {
	return getContext(contextKey);
}
