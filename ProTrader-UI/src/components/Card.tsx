import { type ReactNode } from "react";

type Props = {
  children: ReactNode;
  className?: string;
};

export default function Card({ children, className = "" }: Props) {
  return (
    <section className={`bg-cds-layer rounded-lg shadow-sm border border-cds-border p-4 ${className}`}>
      {children}
    </section>
  );
}

