import type { AnnotationEvent } from '@embedpdf/svelte-pdf-viewer';
import { apiRequest } from '$lib/api/client';
import type { CanonicalAnnotation, CanonicalReply } from '$lib/pdf/annotation-adapter';

type WritableAnnotationEvent = Exclude<AnnotationEvent, { type: 'loaded' }>;
type ReplyIdentity = { itemId: string; annotationId: string; replyId: string };
export type AnnotationReplyApi = {
	create(input: ReplyIdentity & { body: string }): Promise<CanonicalReply>;
	restore(input: ReplyIdentity & { version: number }): Promise<CanonicalReply>;
	update(input: ReplyIdentity & { version: number; body: string }): Promise<CanonicalReply>;
	delete(input: ReplyIdentity & { version: number }): Promise<unknown>;
};

export const annotationReplyApi: AnnotationReplyApi = {
	create: ({ itemId, annotationId, replyId, body }) =>
		apiRequest('POST', '/items/{item_id}/annotations/{annotation_id}/replies', {
			params: { path: { item_id: itemId, annotation_id: annotationId } },
			body: { id: replyId, body }
		}),
	restore: ({ itemId, annotationId, replyId, version }) =>
		apiRequest('POST', '/items/{item_id}/annotations/{annotation_id}/replies/{reply_id}/restore', {
			params: {
				path: { item_id: itemId, annotation_id: annotationId, reply_id: replyId },
				query: { version }
			}
		}),
	update: ({ itemId, annotationId, replyId, version, body }) =>
		apiRequest('PATCH', '/items/{item_id}/annotations/{annotation_id}/replies/{reply_id}', {
			params: { path: { item_id: itemId, annotation_id: annotationId, reply_id: replyId } },
			body: { version, body }
		}),
	delete: ({ itemId, annotationId, replyId, version }) =>
		apiRequest('DELETE', '/items/{item_id}/annotations/{annotation_id}/replies/{reply_id}', {
			params: {
				path: { item_id: itemId, annotation_id: annotationId, reply_id: replyId },
				query: { version }
			}
		})
};

export function selectNativeAnnotationIds(
	annotationIds: Iterable<string>,
	importedIds: { has(id: string): boolean }
): string[] {
	return Array.from(annotationIds).filter((id) => !importedIds.has(id));
}

export function createWriteQueue() {
	let tail: Promise<void> = Promise.resolve();
	let pendingCount = 0;

	return {
		enqueue(operation: () => Promise<void>): Promise<void> {
			let result: Promise<void>;
			if (pendingCount === 0) {
				try {
					result = operation();
				} catch (error) {
					result = Promise.reject(error);
				}
			} else {
				result = tail.catch(() => undefined).then(operation);
			}
			pendingCount += 1;
			tail = result.finally(() => {
				pendingCount -= 1;
			});
			return result;
		},
		flush(): Promise<void> {
			return tail;
		},
		hasPending(): boolean {
			return pendingCount > 0;
		}
	};
}

export async function persistReplyEvent({
	event,
	itemId,
	records,
	tombstones,
	api = annotationReplyApi
}: {
	event: WritableAnnotationEvent;
	itemId: string;
	records: Map<string, CanonicalAnnotation>;
	tombstones: Map<string, CanonicalReply>;
	api?: AnnotationReplyApi;
}): Promise<{ parent: CanonicalAnnotation; reply: CanonicalReply | null } | null> {
	const parentId = event.annotation.inReplyToId;
	if (!parentId) return null;
	const parent = records.get(parentId);
	// EmbedPDF can emit reply removals while a parent annotation is being purged.
	if (!parent) return null;

	const replyId = event.annotation.id;
	const existing = parent.replies.find((reply) => reply.id === replyId);
	let saved: CanonicalReply | null = null;

	if (event.type === 'create') {
		if (existing) return { parent, reply: existing };
		const tombstone = tombstones.get(replyId);
		saved = tombstone
			? await api.restore({
					itemId,
					annotationId: parentId,
					replyId,
					version: tombstone.version
				})
			: await api.create({
					itemId,
					annotationId: parentId,
					replyId,
					body: event.annotation.contents ?? ''
				});
		tombstones.delete(replyId);
		parent.replies = [...parent.replies, saved];
	} else if (event.type === 'update') {
		if (!existing) return null;
		saved = await api.update({
			itemId,
			annotationId: parentId,
			replyId,
			version: existing.version,
			body: event.patch.contents ?? event.annotation.contents ?? ''
		});
		parent.replies = parent.replies.map((reply) => (reply.id === replyId ? saved! : reply));
	} else {
		if (!existing) return null;
		await api.delete({ itemId, annotationId: parentId, replyId, version: existing.version });
		tombstones.set(replyId, { ...existing, version: existing.version + 1 });
		parent.replies = parent.replies.filter((reply) => reply.id !== replyId);
	}

	records.set(parent.id, parent);
	return { parent, reply: saved };
}
