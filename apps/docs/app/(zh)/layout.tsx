import { Inter } from 'next/font/google';
import type { Metadata } from 'next';
import { Provider } from '@/components/provider';
import '@/app/global.css';

const inter = Inter({
  subsets: ['latin'],
});

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL ?? process.env.CF_PAGES_URL ?? 'http://localhost:3000'),
  title: { default: 'twmarket', template: '%s | twmarket' },
  description: '台灣市場資料 Python 套件文件',
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-Hant" className={inter.className} suppressHydrationWarning>
      <body className="flex flex-col min-h-screen">
        <Provider locale="zh-TW">{children}</Provider>
      </body>
    </html>
  );
}
