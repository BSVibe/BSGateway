import { PageBoundary } from '@/src/components/layout/PageBoundary';
import { ApiKeysPage } from '@/src/page-views/ApiKeysPage';

export default function Page() {
  return (
    <PageBoundary>
      <ApiKeysPage />
    </PageBoundary>
  );
}
