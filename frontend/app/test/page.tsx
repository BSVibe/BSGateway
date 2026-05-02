import { PageBoundary } from '@/src/components/layout/PageBoundary';
import { RoutingTestPage } from '@/src/page-views/RoutingTestPage';

export default function Page() {
  return (
    <PageBoundary>
      <RoutingTestPage />
    </PageBoundary>
  );
}
