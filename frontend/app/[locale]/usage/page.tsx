import { PageBoundary } from '@/src/components/layout/PageBoundary';
import { UsagePage } from '@/src/page-views/UsagePage';

export default function Page() {
  return (
    <PageBoundary>
      <UsagePage />
    </PageBoundary>
  );
}
