import { cn } from "@/lib/utils";

interface ModuleCardProps {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  className?: string;
}

export function ModuleCard({ title, subtitle, children, className }: ModuleCardProps) {
  return (
    <div
      className={cn(
        "border border-zinc-800 rounded-xl overflow-hidden bg-zinc-900 shadow-sm",
        className
      )}
    >
      <div className="px-4 py-3 border-b border-zinc-800 flex items-center justify-between">
        <h2 className="font-semibold text-zinc-100">{title}</h2>
        {subtitle && (
          <span className="text-xs text-zinc-500">{subtitle}</span>
        )}
      </div>
      <div className="p-4">{children}</div>
    </div>
  );
}
