export function LoadingSpinner() {
  return (
    <div className="flex items-center justify-center p-8">
      <div className="w-8 h-8 border-4 border-gray-700 border-t-accent-500 rounded-full animate-spin" />
    </div>
  );
}
