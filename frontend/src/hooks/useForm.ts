import { useCallback, useState } from 'react';

interface UseFormOptions<T> {
  initialValues: T;
  onSubmit: (values: T) => Promise<void>;
  validate?: (values: T) => string | null;
}

interface UseFormReturn<T> {
  formData: T;
  setFormData: React.Dispatch<React.SetStateAction<T>>;
  showForm: boolean;
  setShowForm: (show: boolean) => void;
  submitting: boolean;
  createError: string | null;
  setCreateError: (error: string | null) => void;
  handleCreate: () => Promise<void>;
  resetForm: () => void;
}

export function useForm<T>({ initialValues, onSubmit, validate }: UseFormOptions<T>): UseFormReturn<T> {
  const [showForm, setShowForm] = useState(false);
  const [formData, setFormData] = useState<T>(initialValues);
  const [submitting, setSubmitting] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const resetForm = useCallback(() => {
    setFormData(initialValues);
    setShowForm(false);
    setCreateError(null);
  }, [initialValues]);

  const handleCreate = useCallback(async () => {
    if (validate) {
      const error = validate(formData);
      if (error) {
        setCreateError(error);
        return;
      }
    }
    setSubmitting(true);
    setCreateError(null);
    try {
      await onSubmit(formData);
      resetForm();
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : 'Operation failed');
    } finally {
      setSubmitting(false);
    }
  }, [formData, onSubmit, validate, resetForm]);

  return {
    formData,
    setFormData,
    showForm,
    setShowForm,
    submitting,
    createError,
    setCreateError,
    handleCreate,
    resetForm,
  };
}
