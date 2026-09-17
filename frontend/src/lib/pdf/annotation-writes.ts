import type { AnnotationEvent } from '@embedpdf/svelte-pdf-viewer';
import type { CanonicalAnnotation, CanonicalReply } from '$lib/pdf/annotation-adapter';

type WritableAnnotationEvent = Exclude<AnnotationEvent, { type: 'loaded' }>;
type RequestOptions = { method?: string; body?: unknown };
type Request = (path: string, options?: RequestOptions) => Promise<unknown>;

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
	request
}: {
	event: WritableAnnotationEvent;
	itemId: string;
	records: Map<string, CanonicalAnnotation>;
	tombstones: Map<string, CanonicalReply>;
	request: Request;
}): Promise<{ parent: CanonicalAnnotation; reply: CanonicalReply | null } | null> {
	const parentId = event.annotation.inReplyToId;
	if (!parentId) return null;
	const parent = records.get(parentId);
	// EmbedPDF can emit reply removals while a parent annotation is being purged.
	if (!parent) return null;

	const replyId = event.annotation.id;
	const existing = parent.replies.find((reply) => reply.id === replyId);
	const basePath = `/items/${itemId}/annotations/${parentId}/replies/${replyId}`;
	let saved: CanonicalReply | null = null;

	if (event.type === 'create') {
		if (existing) return { parent, reply: existing };
		const tombstone = tombstones.get(replyId);
		saved = tombstone
			? ((await request(`${basePath}/restore?version=${tombstone.version}`, {
					method: 'POST'
				})) as CanonicalReply)
			: ((await request(`/items/${itemId}/annotations/${parentId}/replies`, {
					method: 'POST',
					body: { id: replyId, body: event.annotation.contents ?? '' }
				})) as CanonicalReply);
		tombstones.delete(replyId);
		parent.replies = [...parent.replies, saved];
	} else if (event.type === 'update') {
		if (!existing) return null;
		saved = (await request(basePath, {
			method: 'PATCH',
			body: {
				version: existing.version,
				body: event.patch.contents ?? event.annotation.contents ?? ''
			}
		})) as CanonicalReply;
		parent.replies = parent.replies.map((reply) => (reply.id === replyId ? saved! : reply));
	} else {
		if (!existing) return null;
		await request(`${basePath}?version=${existing.version}`, { method: 'DELETE' });
		tombstones.set(replyId, { ...existing, version: existing.version + 1 });
		parent.replies = parent.replies.filter((reply) => reply.id !== replyId);
	}

	records.set(parent.id, parent);
	return { parent, reply: saved };
}
