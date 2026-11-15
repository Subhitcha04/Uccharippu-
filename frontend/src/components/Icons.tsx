import type { ReactNode } from "react";
const P = (d: ReactNode, size = 20, fill = false) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill={fill ? "currentColor" : "none"} stroke={fill ? "none" : "currentColor"}
    strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden focusable="false">{d}</svg>
);
export const Speaker = () => P(<><path d="M11 5 6 9H3v6h3l5 4z" /><path d="M15.5 8.5a5 5 0 0 1 0 7" /><path d="M18.5 5.5a9 9 0 0 1 0 13" /></>);
export const Pencil = () => P(<><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z" /></>);
export const Check = () => P(<path d="m5 12 5 5L20 7" />);
export const CheckCircle = () => P(<><circle cx="12" cy="12" r="9" /><path d="m8 12.5 3 3 5-6" /></>);
export const Clock = () => P(<><path d="M3 12a9 9 0 1 0 3-6.7" /><path d="M3 4v5h5" /><path d="M12 8v5l3 2" /></>);
export const Play = ({ size = 20 }: { size?: number }) => P(<path d="M8 5v14l11-7z" />, size, true);
export const Stop = () => P(<rect x="6" y="6" width="12" height="12" rx="2" />, 20, true);
export const Download = () => P(<><path d="M12 4v11" /><path d="m7 11 5 5 5-5" /><path d="M5 20h14" /></>);
export const Sun = () => P(<><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></>);
export const Moon = () => P(<path d="M21 13A9 9 0 1 1 11 3a7 7 0 0 0 10 10z" />);
export const More = () => P(<><circle cx="5" cy="12" r="1.4" /><circle cx="12" cy="12" r="1.4" /><circle cx="19" cy="12" r="1.4" /></>, 20, true);
export const Alert = () => P(<><path d="M12 3 2 20h20z" /><path d="M12 10v4" /><path d="M12 17.5v.01" /></>);
export const Person = () => P(<><circle cx="12" cy="8" r="4" /><path d="M4 21a8 8 0 0 1 16 0" /></>);
export const Machine = () => P(<><rect x="5" y="5" width="14" height="14" rx="2" /><path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3" /><rect x="9" y="9" width="6" height="6" rx="1" /></>);
export const Spinner = () => (<svg className="spin" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" aria-hidden><path d="M12 3a9 9 0 1 0 9 9" /></svg>);
export const Wave = () => P(<path d="M3 12h2M7 8v8M11 5v14M15 9v6M19 11v2" />);
