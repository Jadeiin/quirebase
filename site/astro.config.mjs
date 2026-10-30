import starlight from '@astrojs/starlight';
import { defineConfig } from 'astro/config';
import mermaid from 'astro-mermaid';
import starlightLinksValidator from 'starlight-links-validator';
import starlightOpenAPI, { openAPISidebarGroups } from 'starlight-openapi';
import starlightSidebarTopics from 'starlight-sidebar-topics';
import locales from './locales.json' with { type: 'json' };

export default defineConfig({
  site: process.env.QUIREBASE_DOCS_SITE || undefined,
  trailingSlash: 'always',
  integrations: [
    mermaid({ autoTheme: true, enableLog: false }),
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
      locales,
      plugins: [
        starlightSidebarTopics(
          [
            {
              label: { en: 'User guide', 'zh-CN': '使用指南' },
              link: '/getting-started/quickstart/',
              icon: 'open-book',
              id: 'guides',
              items: [
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
                    'guides/tags',
                    'guides/keyboard-shortcuts',
                    'guides/files',
                    'guides/pdf-annotations',
                    'guides/collaboration',
                    'guides/discussions',
                    'guides/citations-and-exports',
                    'guides/citation-styles',
                    'guides/account',
                  ],
                },
                {
                  label: 'Concepts',
                  translations: { 'zh-CN': '核心概念' },
                  items: ['concepts/research-library', 'concepts/workspaces-and-projects'],
                },
                {
                  label: 'Knowledge base',
                  translations: { 'zh-CN': '知识库' },
                  items: ['knowledge-base/faq', 'knowledge-base/troubleshooting'],
                },
              ],
            },
            {
              label: { en: 'Administration', 'zh-CN': '部署与管理' },
              link: '/administration/deployment/',
              icon: 'setting',
              items: [
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
              ],
            },
            {
              label: { en: 'Developers', 'zh-CN': '开发与集成' },
              link: '/developers/http-api/',
              icon: 'seti:json',
              id: 'developers',
              items: [
                {
                  label: 'Developers',
                  translations: { 'zh-CN': '开发与集成' },
                  items: ['developers/http-api', 'developers/mcp', 'developers/contributing'],
                },
                ...openAPISidebarGroups,
              ],
            },
          ],
          {
            topics: {
              guides: ['/404', '/zh-cn/404'],
              developers: ['/reference/api', '/reference/api/**/*'],
            },
          },
        ),
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
