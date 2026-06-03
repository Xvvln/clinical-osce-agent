import * as React from "react";

import { cn } from "@/lib/utils";

type BadgeVariant = "default" | "success" | "warning" | "danger" | "muted";

const badgeClassNames: Record<BadgeVariant, string> = {
  default: "border-[#D9CCBB] bg-white text-[#141413]",
  success: "border-emerald-200 bg-emerald-50 text-emerald-700",
  warning: "border-amber-200 bg-amber-50 text-amber-700",
  danger: "border-red-200 bg-red-50 text-red-700",
  muted: "border-[#E7E0D4] bg-[#F7F4ED] text-[#6F6257]",
};

export function Badge({
  className,
  variant = "default",
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & Readonly<{ variant?: BadgeVariant }>) {
  return (
    <span
      className={cn("inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-medium", badgeClassNames[variant], className)}
      {...props}
    />
  );
}
