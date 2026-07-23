import type { HTMLAttributes, ReactNode } from "react";

export type BidiTextProps = Readonly<{
  children: ReactNode;
  className?: string;
}> &
  Omit<HTMLAttributes<HTMLElement>, "children" | "dir">;

export function BidiText({ children, className, ...props }: BidiTextProps) {
  return (
    <bdi
      {...props}
      className={["font-mono", className].filter(Boolean).join(" ")}
      dir="ltr"
      translate="no"
    >
      {children}
    </bdi>
  );
}
