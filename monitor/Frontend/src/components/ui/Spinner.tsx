import { Loader2 } from 'lucide-react';

export function Spinner({ size = 24 }: { size?: number }) {
  return (
    <Loader2 
      size={size} 
      className="text-white spinner"
      style={{ opacity: 0.7 }}
    />
  );
}
