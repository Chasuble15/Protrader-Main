import { type ReactNode } from "react";

type Props = {
  children: ReactNode;
  className?: string;
};

export default function Card({ children, className = "" }: Props) {
  return (
    <section className={`bg-white/80 backdrop-blur rounded-xl shadow-sm ring-1 ring-slate-200 p-4 ${className}`}>
      {children}
    </section>
  );
}

