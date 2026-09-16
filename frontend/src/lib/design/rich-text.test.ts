import { describe, expect, it } from 'vitest';
import { projectRichText } from '$lib/design/rich-text';

describe('Web rich-text projection', () => {
	it('converts every inline TeX span to allowlisted MathML inside canonical markup', () => {
		const rendered = projectRichText(String.raw`Energy $E_{mc}\in\mathbb{R}$ and <i>$x^2$</i>`);

		expect(rendered.match(/<math/g)).toHaveLength(2);
		expect(rendered).toContain('<i><math');
		expect(rendered).toContain('<msub>');
		expect(rendered).toContain('<msup>');
		expect(rendered).not.toContain('$E_');
	});

	it('drops elements and attributes outside the rich-text and MathML allowlists', () => {
		const rendered = projectRichText(
			String.raw`<script>alert(1)</script>$\href{javascript:alert(1)}{x}$`
		);

		expect(rendered).not.toContain('<script');
		expect(rendered).not.toContain('href=');
		expect(rendered).not.toContain('javascript:');
		expect(rendered).toContain('<mi>x</mi>');
	});

	it('falls back to literal text for malformed or oversized TeX spans', () => {
		const malformed = projectRichText(String.raw`Invalid $\frac{$ formula`);
		const oversized = projectRichText(`$${'x'.repeat(201)}$`);

		expect(malformed).toBe(String.raw`Invalid $\frac{$ formula`);
		expect(oversized).toBe(`$${'x'.repeat(201)}$`);
		expect(malformed).not.toContain('<math');
		expect(oversized).not.toContain('<math');
	});

	it('keeps currency dollars outside the inline-math grammar', () => {
		const rendered = projectRichText('Costs $5 and $10; US$5 and CA$10');

		expect(rendered).toBe('Costs $5 and $10; US$5 and CA$10');
		expect(rendered).not.toContain('<math');
	});

	it('rebuilds canonical rich text without source attributes or unknown elements', () => {
		const rendered = projectRichText(
			'<i onclick="alert(1)">Visible</i><span data-source="x"> text</span><img src=x onerror=alert(1)>'
		);

		expect(rendered).toBe('<i>Visible</i> text');
		expect(rendered).not.toContain('onclick');
		expect(rendered).not.toContain('data-source');
		expect(rendered).not.toContain('<img');
	});
});
