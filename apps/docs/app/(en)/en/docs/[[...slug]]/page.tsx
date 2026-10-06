import { DocumentationPage, documentationMetadata } from '@/lib/docs-page';
import { source } from '@/lib/source';

interface Props { params: Promise<{ slug?: string[] }>; }

export default async function Page({ params }: Props) {
  return <DocumentationPage slugs={(await params).slug} locale="en" />;
}

export function generateStaticParams() {
  return source.getPages('en').map((page) => ({ slug: page.slugs }));
}

export async function generateMetadata({ params }: Props) {
  return documentationMetadata((await params).slug, 'en');
}
