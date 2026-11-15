import { useEffect, useState, type ReactNode } from "react";

/** Smooth open/close for edit and history panels. Content is unmounted after it has closed, and inert while closing. */
export default function Collapse({ open, children, area }: { open: boolean; children: ReactNode; area?: string }) {
  const [render, setRender] = useState(open);
  useEffect(() => {
    if (open) { setRender(true); return; }
    const t = window.setTimeout(() => setRender(false), 280);
    return () => window.clearTimeout(t);
  }, [open]);
  return (
    <div className={"collapse" + (open ? " open" : "") + (area ? " " + area : "")} {...({ inert: open ? undefined : "" } as object)}>
      <div className="collapse-inner">{render ? children : null}</div>
    </div>
  );
}
