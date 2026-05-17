import { PageBoundary } from '@/src/components/layout/PageBoundary';
import { RoutesPage } from '@/src/page-views/RoutesPage';

export default function Page() {
  return (
    <PageBoundary>
      <RoutesPage />
    </PageBoundary>
  );
}
