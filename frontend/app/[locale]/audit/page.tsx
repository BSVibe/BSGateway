import { PageBoundary } from '@/src/components/layout/PageBoundary';
import { AuditPage } from '@/src/page-views/AuditPage';

export default function Page() {
  return (
    <PageBoundary>
      <AuditPage />
    </PageBoundary>
  );
}
