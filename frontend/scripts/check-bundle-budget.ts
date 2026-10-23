import { readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { gzipSync } from 'node:zlib';

type ManifestEntry = {
	file: string;
	name?: string;
	imports?: string[];
	dynamicImports?: string[];
	css?: string[];
	assets?: string[];
};

type BundleSize = { raw: number; gzip: number };

const outputDirectory = '.svelte-kit/output/client';
const manifest = JSON.parse(
	readFileSync(join(outputDirectory, '.vite/manifest.json'), 'utf8')
) as Record<string, ManifestEntry>;
const generatedApp = readFileSync('.svelte-kit/generated/build/client/app.js', 'utf8');

function manifestKeyByName(name: string): string {
	const match = Object.entries(manifest).find(([, entry]) => entry.name === name);
	if (!match) throw new Error(`Bundle manifest entry not found: ${name}`);
	return match[0];
}

function routeNodes(route: string): string[] {
	const escaped = route.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
	const match = generatedApp.match(new RegExp(`"${escaped}": \\[(\\d+),\\[([^\\]]*)\\]\\]`));
	if (!match) throw new Error(`SvelteKit route node not found: ${route}`);
	const layouts = match[2]
		.split(',')
		.map((value) => value.trim())
		.filter(Boolean);
	return [0, ...layouts, match[1]].map((index) => manifestKeyByName(`nodes/${index}`));
}

function dependencyGraph(roots: string[], includeDynamicImports: boolean): Set<string> {
	const graph = new Set<string>();
	const pending = [...roots];
	while (pending.length) {
		const key = pending.pop();
		if (!key || graph.has(key)) continue;
		const entry = manifest[key];
		if (!entry) throw new Error(`Bundle dependency not found: ${key}`);
		graph.add(key);
		pending.push(...(entry.imports ?? []));
		if (includeDynamicImports) pending.push(...(entry.dynamicImports ?? []));
	}
	return graph;
}

function mergeGraphs(...graphs: Set<string>[]): Set<string> {
	return new Set(graphs.flatMap((graph) => [...graph]));
}

function graphFiles(graph: Set<string>): Set<string> {
	const files = new Set<string>();
	for (const key of graph) {
		const entry = manifest[key];
		files.add(entry.file);
		for (const file of entry.css ?? []) files.add(file);
		for (const file of entry.assets ?? []) files.add(file);
	}
	return files;
}

function bundleSize(files: Set<string>): BundleSize {
	let raw = 0;
	let gzip = 0;
	for (const file of files) {
		const path = join(outputDirectory, file);
		const contents = readFileSync(path);
		raw += statSync(path).size;
		gzip += gzipSync(contents).byteLength;
	}
	return { raw, gzip };
}

function format(bytes: number): string {
	return `${(bytes / 1024).toFixed(1)} KiB`;
}

function enforce(name: string, actual: BundleSize, budget: BundleSize) {
	console.log(`${name}: ${format(actual.raw)} raw, ${format(actual.gzip)} gzip`);
	if (actual.raw > budget.raw || actual.gzip > budget.gzip) {
		throw new Error(
			`${name} exceeds its budget (${format(budget.raw)} raw, ${format(budget.gzip)} gzip)`
		);
	}
}

const runtime = [manifestKeyByName('entry/start'), manifestKeyByName('entry/app')];
const dashboard = dependencyGraph([...runtime, ...routeNodes('/(app)')], false);
const library = dependencyGraph(
	[...runtime, ...routeNodes('/(app)/workspace/[workspaceId]/library')],
	false
);
const quickNavigationKey = manifestKeyByName('QuickNavigationDialog');
if (dashboard.has(quickNavigationKey) || library.has(quickNavigationKey))
	throw new Error('Quick navigation results must load only when the navigation dialog opens');
const quickNavigation = mergeGraphs(dashboard, dependencyGraph([quickNavigationKey], false));
const libraryRefinementsKey = manifestKeyByName('LibraryRefinements');
if (dashboard.has(libraryRefinementsKey) || library.has(libraryRefinementsKey))
	throw new Error('Library refinement code must load only when the filter panel opens');
const libraryRefinements = mergeGraphs(library, dependencyGraph([libraryRefinementsKey], false));
const libraryPreviewKey = manifestKeyByName('LibraryPreview');
if (dashboard.has(libraryPreviewKey) || library.has(libraryPreviewKey))
	throw new Error('Item preview code must load only when the Library preview opens');
const libraryPreview = mergeGraphs(library, dependencyGraph([libraryPreviewKey], false));
const libraryOrganizeKey = manifestKeyByName('LibraryPreviewOrganize');
if (dashboard.has(libraryOrganizeKey) || libraryPreview.has(libraryOrganizeKey))
	throw new Error('Inline organization code must load only when organization opens');
const metadataEditorKey = manifestKeyByName('SchemaMetadataEditor');
if (dashboard.has(metadataEditorKey))
	throw new Error('Schema editor code leaked into the application shell');
const pdfRouteNodes = routeNodes('/(app)/workspace/[workspaceId]/item/[itemId]/pdf/[revisionId]');
const pdfReader = mergeGraphs(
	dependencyGraph([...runtime, ...pdfRouteNodes], false),
	dependencyGraph([pdfRouteNodes.at(-1)!], true)
);

// Initial route sizes exclude lazy imports; opened editors and readers include them separately.
function routeBundle(route: string): BundleSize {
	return bundleSize(graphFiles(dependencyGraph([...runtime, ...routeNodes(route)], false)));
}

const dashboardPdfDependencies = [...dashboard].filter((key) => {
	const entry = manifest[key];
	return (
		entry.name?.toLowerCase().includes('embedpdf') ||
		(entry.assets ?? []).some((asset) => asset.includes('pdfium'))
	);
});
if (dashboardPdfDependencies.length) {
	throw new Error(
		`PDF reader code leaked into the application shell: ${dashboardPdfDependencies.join(', ')}`
	);
}

if ([...dashboard].some((key) => manifest[key].name === 'DateField')) {
	throw new Error('DatePicker code leaked into the application shell');
}

// Workspace navigation, confirmation feedback and both locale catalogs add shared code/styles.
// Route budgets include that shared graph; settings sections remain independently loaded.
// Received invitations add a pending-count query/menu entry and both locale catalogs to the shell.
// Measured against 4fea97a: +7237 B raw / +1897 B gzip shared; Library also retains a delete snapshot.
// Leave translations add 1741 B raw / 373 B gzip to the shell; confirmation stays in settings.
// Access-loss cleanup adds 485 B raw / 284 B gzip to Workspace routes. Route-independent leave
// verification adds 165 B raw / 81 B gzip to General settings.
// Library table styles and both locale catalogs add 4864 B raw / 1520 B gzip shared vs 8b9f138.
// Its route-specific table/selection/display controls add 57475 B raw / 16737 B gzip.
// Structured author links and contextual metadata filters add about 3 KiB raw to Library.
// Shared link styles add under 100 B raw; only exceeded shared-route limits move below.
// Sorting adds shared icons/catalog entries and about 4 KiB to Library. Only exceeded limits
// move to the next 1 kB raw / 500 B gzip boundary; isolation checks stay unchanged.
// First-author sorting and the consolidated results toolbar add about 1 KiB to Library.
// Icon view segments add about 14 KiB raw / 4.5 KiB gzip to Library through Skeleton’s radio
// behavior; shared icons, translations and styles add under 1 KiB raw to other routes.
// Joined sorting controls and their order hint add 645 B raw / about 150 B gzip shared.
// Project access-loss cleanup adds under 1 KiB raw to shared query code.
// Nineteen shortcut messages add 2424 B raw / about 750 B gzip to the shared catalogs.
// Mounted hotkeys and row commands add about 33 kB raw / 11.5 kB gzip to Library.
// Shared runtime, the keyboard glyph and focus styles add about 6 kB raw / 1 kB gzip.
// Selection hints and toolbar styles add 1894 B raw / about 420 B gzip to shared code.
// Range selection and scoped completion focus add about 2.3 kB raw to Library.
// Continuous preview, inline organization and return-context labels add shared catalog/styles code.
// Inline organization stays a separate lazy graph (about 10 kB raw / 4 kB gzip).
// Only exceeded budgets move to the next 1 kB raw / 500 B gzip boundary.
// Bulk-removal preview reconciliation adds about 1 kB raw to the Library graph.
// Library Item actions and lazy Project selectors add shared labels/styles and route-owned code.
// Measured budgets retain separate lazy preview and organization checks.
// Explicit scan coverage adds shared translations; retained citation recovery and refreshed
// PDF selection add about 2.4 kB raw to Item sections. Only exceeded limits move below.
// Project scope navigation and retained return context add route-owned code to Library.
// Only exceeded Library/preview limits move to the next 1 kB raw / 500 B gzip boundary.
// Saved views add route-owned storage/dialog code; refinement values remain a lazy graph.
// Their labels add shared catalog bytes; only exceeded limits move to the same boundaries.
// Cross-tab saved-view locking and pending interaction guards add about 1.1 kB raw to Library.
// Global TanStack hotkeys and navigation add about 47 kB raw / 17 kB gzip to the shell;
// Library shares its existing hotkey runtime. Dialog results stay lazy (about 10 kB / 4 kB).
// Only exceeded dimensions move to the next 1 kB raw / 500 B gzip boundary.
// Recoverable import destinations and both catalogs add shared code; batch UI stays route-owned.
// Raise only exceeded dimensions to the same 1 kB raw / 500 B gzip boundaries.
// Retention diagnostics and Import history add ~3.5 KiB raw / 0.7 KiB gzip to shared
// catalogs/tracking; Import and Maintenance keep their extra controls in route-owned code.
// The separate history route and explicit action labels add ~1 KiB raw / 0.4 KiB gzip
// to shared catalogs/route registration. Only exceeded dimensions move to the same boundaries.
// Admin tables and deferred operational details add shared translations;
// controls stay in Admin routes. Only exceeded dimensions move to the
// existing 1 kB raw / 500 B gzip boundaries, including the expanded Admin route graphs.
// Joined Admin sort controls stay in those routes; Maintenance no longer loads history rows.
// Workspace governance adds paginated tables, target lookup and detail recovery to Admin;
// its additional labels remain in the shared catalogs and use the same budget boundaries.
// Responsive filter alignment stays in Admin-owned CSS; pagination controls share one height.
// Only exceeded dimensions move to the existing budget boundaries after measuring the build.
// Citation Style pagination, source filtering, sorting and the collapsible installer
// add ~13 KiB raw / 4 KiB gzip to Tools. Shared labels use the same budget boundaries.
// Default-style pagination and exact-key recovery add shared query code and labels.
// Current-page refinements and credited author labels add ~1 KiB to Library plus shared catalogs.
// Only measured overages move to the next 1 kB raw / 500 B gzip boundary.
// Discovery labels grow shared catalogs; search and validated Import-return parsing stay route-owned.
// Typed, grouped presence choices reuse selectors; IDs and draft conversion stay route-owned.
// Session/invitation retry states and localized failures add shared code/catalogs.
// Measured Library overages use the existing 1 kB raw / 500 B gzip boundaries.
// Resizable PDF sidebars add 688 B raw / up to 45 B gzip to shared CSS/catalogs vs 97fc157;
// interaction code stays in the PDF reader. Only exceeded preview/organization dimensions move
// to the existing 1 kB raw / 500 B gzip boundaries.
enforce('Application shell', bundleSize(graphFiles(dashboard)), {
	// Includes shared Invitation and owner-governance navigation and translations.
	raw: 795000,
	gzip: 224500
});
enforce('Quick navigation when open', bundleSize(graphFiles(quickNavigation)), {
	raw: 806000,
	gzip: 229500
});
enforce('Library route', bundleSize(graphFiles(library)), {
	raw: 1138000,
	// Includes whole-name author folding, scoped selection cleanup and last-page recovery.
	gzip: 330000
});
enforce('Library refinements when open', bundleSize(graphFiles(libraryRefinements)), {
	raw: 1142000,
	gzip: 331500
});
enforce(
	'Library preview when open',
	bundleSize(graphFiles(libraryPreview)),
	// Bibliographic preview and scoped navigation add about 14 kB raw / 5.5 kB gzip on demand.
	{ raw: 1152000, gzip: 335000 }
);
enforce(
	'Library organization when open',
	bundleSize(graphFiles(mergeGraphs(libraryPreview, dependencyGraph([libraryOrganizeKey], false)))),
	{ raw: 1164000, gzip: 340000 }
);
enforce('Discovery route', routeBundle('/(app)/workspace/[workspaceId]/discovery'), {
	// Includes shared pagination, Invitation lifecycle and open reassignment form translations.
	raw: 946000,
	gzip: 272000
});
enforce('Account route', routeBundle('/(app)/account'), {
	raw: 913000,
	gzip: 260500
});
enforce('Tools route', routeBundle('/(app)/workspace/[workspaceId]/tools'), {
	// Includes shared pagination styles, account-management translations and recovery controls.
	raw: 947000,
	gzip: 274500
});
enforce('Import route', routeBundle('/(app)/workspace/[workspaceId]/import'), {
	raw: 934000,
	gzip: 273500
});
enforce('Import history route', routeBundle('/(app)/workspace/[workspaceId]/import/history'), {
	raw: 851000,
	gzip: 246000
});
enforce(
	'Item overview route',
	routeBundle('/(app)/workspace/[workspaceId]/item/[itemId]/(sections)'),
	{
		raw: 926000,
		gzip: 268500
	}
);
enforce(
	'Item metadata route',
	routeBundle('/(app)/workspace/[workspaceId]/item/[itemId]/(sections)/metadata'),
	{
		raw: 921000,
		gzip: 267500
	}
);
enforce(
	'Item files route',
	routeBundle('/(app)/workspace/[workspaceId]/item/[itemId]/(sections)/files'),
	{
		raw: 973000,
		gzip: 284000
	}
);
enforce(
	'Item organize route',
	routeBundle('/(app)/workspace/[workspaceId]/item/[itemId]/(sections)/organize'),
	{
		raw: 929000,
		// Organize now includes the destructive-detachment confirmation dialog.
		gzip: 270500
	}
);
enforce(
	'Item annotations route',
	routeBundle('/(app)/workspace/[workspaceId]/item/[itemId]/(sections)/annotations'),
	{
		// Includes shared pagination styles and account-management translations.
		raw: 935000,
		gzip: 272000
	}
);
enforce(
	'Item discussion route',
	routeBundle('/(app)/workspace/[workspaceId]/item/[itemId]/(sections)/discussion'),
	{
		// Includes shared pagination styles and account-management translations.
		raw: 922000,
		gzip: 268500
	}
);
enforce('Admin overview route', routeBundle('/(app)/admin'), {
	// Includes Skeleton pagination and the separate Invitation navigation entry.
	raw: 834000,
	gzip: 238000
});
enforce('Admin users route', routeBundle('/(app)/admin/users'), {
	// Includes account containment guidance and expandable role and sign-in controls.
	raw: 847000,
	gzip: 243000
});
enforce('Admin invitations route', routeBundle('/(app)/admin/invitations'), {
	// Owns invitation creation, history, status filtering and one pagination control.
	raw: 845000,
	gzip: 242000
});
enforce('Admin workspaces route', routeBundle('/(app)/admin/workspaces'), {
	// Includes owner reassignment, bounded User search, conflict recovery and scoped completion.
	raw: 913000,
	gzip: 263500
});
enforce('Admin audit route', routeBundle('/(app)/admin/audit'), {
	// Includes the separate Invitation navigation entry and shared translations.
	raw: 840000,
	gzip: 240000
});
enforce('Admin workflows route', routeBundle('/(app)/admin/workflows'), {
	// Includes Skeleton pagination and the separate Invitation navigation entry.
	raw: 841000,
	gzip: 240500
});
enforce('Admin settings route', routeBundle('/(app)/admin/settings'), {
	// Includes the separate Invitation navigation entry and shared translations.
	raw: 822000,
	gzip: 235000
});
enforce('Admin maintenance route', routeBundle('/(app)/admin/maintenance'), {
	// Includes the separate Invitation navigation entry and shared translations.
	raw: 824000,
	gzip: 235500
});
// Includes the conditional received-invitation section; no standalone inbox route.
enforce('Workspace directory', routeBundle('/(app)/workspace'), { raw: 844000, gzip: 241500 });
enforce('Workspace general settings', routeBundle('/(app)/workspace/[workspaceId]/settings'), {
	raw: 826000,
	gzip: 237500
});
// Paginated collaboration tables and filters stay in their respective routes.
// Shared labels and query recovery move only exceeded dimensions to the existing boundaries.
enforce('Workspace members', routeBundle('/(app)/workspace/[workspaceId]/settings/members'), {
	raw: 854000,
	gzip: 247000
});
enforce(
	'Workspace invitations',
	routeBundle('/(app)/workspace/[workspaceId]/settings/invitations'),
	{ raw: 850000, gzip: 245500 }
);
enforce(
	'Workspace advanced settings',
	routeBundle('/(app)/workspace/[workspaceId]/settings/advanced'),
	{ raw: 830000, gzip: 239000 }
);
enforce('PDF reader route', bundleSize(graphFiles(pdfReader)), {
	raw: 8000000,
	gzip: 3100000
});

const metadataRoute = '/(app)/workspace/[workspaceId]/item/[itemId]/(sections)/metadata';
const openedEditor = mergeGraphs(
	dependencyGraph([...runtime, ...routeNodes(metadataRoute)], false),
	dependencyGraph([metadataEditorKey], true)
);
enforce('Metadata editor when open', bundleSize(graphFiles(openedEditor)), {
	// Includes shared pagination styles and account-management translations.
	raw: 1165000,
	gzip: 337500
});
