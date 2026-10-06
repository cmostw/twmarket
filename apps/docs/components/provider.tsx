'use client';

import SearchDialog from '@/components/search';
import { zhTW } from '@fumadocs/language/zh-tw';
import { i18n } from '@/lib/i18n';
import { i18nProvider, uiTranslations } from 'fumadocs-ui/i18n';
import { RootProvider } from 'fumadocs-ui/provider/next';
import { type ReactNode } from 'react';

const translations = i18n.translations().extend(uiTranslations()).preset('zh-TW', zhTW()).add({
  en: { displayName: 'English' },
  'zh-TW': { displayName: '繁體中文' },
});

export function Provider({ children, locale }: { children: ReactNode; locale: string }) {
  return (
    <RootProvider search={{ SearchDialog }} i18n={i18nProvider(translations, locale)}>
      {children}
    </RootProvider>
  );
}
