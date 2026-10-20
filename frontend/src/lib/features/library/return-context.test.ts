import { expect, it } from 'vitest';
import {
	libraryItemHref,
	libraryReturnHref,
	libraryReturnItemId,
	libraryReturnTo,
	readLibraryReturnTo
} from './return-context.js';

it('preserves submitted Library filters, sorting, paging and preview without nested state', () => {
	const current = new URL(
		'https://app.example/workspace/workspace-1/library?q=研究+%26+ML&project=project-1&tag=tag-1&sort=author&direction=desc&page=3&page_size=50&author_first_name=&preview=item-2&return_to=ignored&unrelated=value'
	);
	const context = libraryReturnTo('workspace-1', current, 'item-1');
	expect(context).toBe(
		'workspace/workspace-1/library?q=%E7%A0%94%E7%A9%B6+%26+ML&tag=tag-1&project=project-1&sort=author&direction=desc&author_first_name=&page=3&page_size=50&preview=item-2#library-item-item-1'
	);
	const item = new URL(`/${libraryItemHref('workspace-1', 'item-1', 'files', context)}`, current);
	expect(item.pathname).toBe('/workspace/workspace-1/item/item-1/files');
	expect(readLibraryReturnTo('workspace-1', item.searchParams)).toBe(context);
	expect(libraryReturnHref('workspace-1', item.searchParams)).toBe(context);
});

it.each([
	'https://evil.example/workspace/workspace-1/library',
	'https://app.example/workspace/workspace-1/library',
	'//evil.example/workspace/workspace-1/library',
	'/workspace/workspace-2/library',
	'/workspace/workspace-1/library/../item/item-1',
	'/workspace/workspace-1/item/../library',
	'/workspace/workspace-1/%6cibrary',
	'/workspace/workspace-1/library/',
	'/workspace/workspace-1/library\\anything',
	'/workspace/workspace-1/library?q=%E0%A4%A',
	'/workspace/workspace-1/library?q=%ZZ',
	'/workspace/workspace-1/library\n',
	'javascript:alert(1)'
])('rejects an unsafe, out-of-scope or malformed return destination: %s', (value) => {
	expect(libraryReturnTo('workspace-1', value)).toBeNull();
	const parameters = new URLSearchParams({ return_to: value });
	expect(libraryReturnHref('workspace-1', parameters)).toBe('workspace/workspace-1/library');
	expect(libraryItemHref('workspace-1', 'item-1', 'files', value)).toBe(
		'workspace/workspace-1/item/item-1/files'
	);
});

it('keeps native direct Item links and adds context after existing PDF annotation parameters', () => {
	expect(libraryItemHref('workspace-1', 'item-1')).toBe('workspace/workspace-1/item/item-1');
	expect(libraryReturnHref('workspace-1', new URLSearchParams())).toBe(
		'workspace/workspace-1/library'
	);
	const href = libraryItemHref(
		'workspace-1',
		'item-1',
		'pdf/revision-1?project_id=project-1',
		'/workspace/workspace-1/library?project=project-1'
	);
	const url = new URL(href, 'https://app.example/');
	expect(url.pathname).toBe('/workspace/workspace-1/item/item-1/pdf/revision-1');
	expect(url.searchParams.get('project_id')).toBe('project-1');
	expect(readLibraryReturnTo('workspace-1', url.searchParams)).toBe(
		'workspace/workspace-1/library?project=project-1'
	);
});

it('removes only the deleted Item preview and anchor while keeping the Library query', () => {
	const parameters = new URLSearchParams({
		return_to:
			'workspace/workspace-1/library?tag=tag-1&sort=title&page=3&preview=item-1#library-item-item-1'
	});
	expect(libraryReturnHref('workspace-1', parameters, { deletedItemId: 'item-1' })).toBe(
		'workspace/workspace-1/library?tag=tag-1&sort=title&page=3'
	);
	expect(libraryReturnHref('workspace-1', parameters, { deletedItemId: 'item-2' })).toBe(
		parameters.get('return_to')
	);
});

it('bounds return anchors and drops unrelated fragments and invalid previews', () => {
	expect(libraryReturnItemId('#library-item-item-1')).toBe('item-1');
	for (const hash of [
		'#arbitrary',
		'#library-item-',
		'#library-item-../item',
		'#library-item-%23x'
	])
		expect(libraryReturnItemId(hash)).toBeNull();
	expect(
		libraryReturnTo('workspace-1', '/workspace/workspace-1/library?preview=../item#unrelated')
	).toBe('workspace/workspace-1/library');
	expect(libraryReturnTo('workspace-1', '/workspace/workspace-1/library', 'item-1')).toBe(
		'workspace/workspace-1/library#library-item-item-1'
	);
});
