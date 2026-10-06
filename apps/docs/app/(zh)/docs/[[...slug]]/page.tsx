import { DocumentationPage, documentationMetadata } from '@/lib/docs-page';
import { source } from '@/lib/source';

interface Props { params: Promise<{ slug?: string[] }>; }

export default async function Page({ params }: Props) {
  return <DocumentationPage slugs={(await params).slug} locale="zh-TW" />;
}

export function generateStaticParams() {
  return source.getPages('zh-TW').map((page) => ({ slug: page.slugs }));
}

export async function generateMetadata({ params }: Props) {
  return documentationMetadata((await params).slug, 'zh-TW');
}
