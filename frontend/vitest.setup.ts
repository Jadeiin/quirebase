import { i18n } from '@lingui/core';
import { DEFAULT_LOCALE } from './src/lib/locale';
import { messages as englishMessages } from './src/lib/locales/en-US/messages';
import { messages as chineseMessages } from './src/lib/locales/zh-CN/messages';

i18n.load({ 'en-US': englishMessages, 'zh-CN': chineseMessages });
i18n.activate(DEFAULT_LOCALE);
