import type { ItemSummary } from '$lib/api/client';
import type { components } from '$lib/api/schema';

export type ItemDetail = ItemSummary & {
	metadata: components['schemas']['ItemMetadata-Input'];
	abstract_html: string | null;
};

export type FileRow = components['schemas']['FileView'];
export type FilesView = components['schemas']['DocumentListView'];
export type OrganizeView = components['schemas']['ItemOrganizeView'];
export type DiscussionMessage = components['schemas']['DiscussionMessageView'];
