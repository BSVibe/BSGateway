import { PageBoundary } from '@/src/components/layout/PageBoundary';
import { DashboardPage } from '@/src/page-views/DashboardPage';

export default function Page() {
  return (
    <PageBoundary>
      <DashboardPage />
    </PageBoundary>
  );
}
