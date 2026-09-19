import type { Page } from '@playwright/test';

export const defaultCitationKeyFormula = 'auth.capitalize + year + shorttitle(1).capitalize';

export async function mockSession(page: Page, role: 'member' | 'administrator' = 'member') {
	await page.route('**/api/v1/session', (route) =>
		route.fulfill({
			json: {
				authenticated: true,
				user: { id: 'user-1', username: 'reader', role }
			}
		})
	);
}

export function minimalPdf(): Buffer {
	const objects = [
		'1 0 obj\n<</Type/Catalog/Pages 2 0 R>>\nendobj\n',
		'2 0 obj\n<</Type/Pages/Kids[3 0 R]/Count 1>>\nendobj\n',
		'3 0 obj\n<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 400]>>\nendobj\n'
	];
	let body = '%PDF-1.4\n';
	const offsets = objects.map((object) => {
		const offset = Buffer.byteLength(body);
		body += object;
		return offset;
	});
	const xref = Buffer.byteLength(body);
	body += `xref\n0 4\n0000000000 65535 f \n${offsets.map((offset) => `${String(offset).padStart(10, '0')} 00000 n `).join('\n')}\n`;
	body += `trailer\n<</Size 4/Root 1 0 R>>\nstartxref\n${xref}\n%%EOF\n`;
	return Buffer.from(body);
}
