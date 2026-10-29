import starlight from '@astrojs/starlight';
import { defineConfig } from 'astro/config';
import starlightLinksValidator from 'starlight-links-validator';
import starlightOpenAPI, { openAPISidebarGroups } from 'starlight-openapi';

export default defineConfig({
  site: process.env.QUIREBASE_DOCS_SITE || undefined,
  trailingSlash: 'always',
  integrations: [
    starlight({
      title: 'Quirebase',
      description: 'User guides, administration, and integrations for a collaborative research library.',
      favicon: '/favicon.svg',
      social: [{ icon: 'github', label: 'GitHub', href: 'https://github.com/Jadeiin/quirebase' }],
      editLink: {
        baseUrl: 'https://github.com/Jadeiin/quirebase/edit/main/site/',
      },
      components: {
        LanguageSelect: './src/components/LanguageSelect.astro',
      },
      locales: {
        root: { label: 'English', lang: 'en' },
        'zh-cn': { label: '简体中文', lang: 'zh-CN' },
      },
      // Sidebar translation keys use the language tag, not the locale's URL prefix.
      sidebar: [
        {
          label: 'Start here',
          translations: { 'zh-CN': '开始使用' },
          items: ['getting-started/quickstart'],
        },
        {
          label: 'User guides',
          translations: { 'zh-CN': '用户指南' },
          items: [
            'guides/discovery',
            'guides/import',
            'guides/library-management',
            'guides/files',
            'guides/pdf-annotations',
            'guides/collaboration',
            'guides/citations-and-exports',
            'guides/account',
          ],
        },
        {
          label: 'Concepts',
          translations: { 'zh-CN': '核心概念' },
          items: ['concepts/research-library', 'concepts/workspaces-and-projects'],
        },
        {
          label: 'Administration',
          translations: { 'zh-CN': '部署与管理' },
          items: [
            'administration/deployment',
            'administration/configuration',
            'administration/workspaces-and-members',
            'administration/maintenance',
          ],
        },
        {
          label: 'Developers',
          translations: { 'zh-CN': '开发与集成' },
          items: ['developers/http-api', 'developers/mcp', 'developers/contributing'],
        },
        {
          label: 'Knowledge base',
          translations: { 'zh-CN': '知识库' },
          items: ['knowledge-base/faq', 'knowledge-base/troubleshooting'],
        },
        ...openAPISidebarGroups,
      ],
      plugins: [
        starlightOpenAPI([
          {
            base: 'reference/api',
            schema: './public/openapi.json',
            sidebar: { label: 'API Reference', operations: { badges: true } },
          },
        ]),
        starlightLinksValidator({
          errorOnFallbackPages: true,
          errorOnInconsistentLocale: true,
          // The OpenAPI plugin supplies this route outside the docs collection.
          // check:build validates the generated routes and their links in the final HTML.
          exclude: ['/reference/api/'],
        }),
      ],
    }),
  ],
});
