import { PageBoundary } from '@/src/components/layout/PageBoundary';
import { ModelsPage } from '@/src/page-views/ModelsPage';

export default function Page() {
  return (
    <PageBoundary>
      <ModelsPage />
    </PageBoundary>
  );
}
