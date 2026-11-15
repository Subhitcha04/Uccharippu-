/** Four voice bars over a wave line: the sound of an auction at the water's edge. */
export default function Logo({ size = 40 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" role="img" aria-label="Uccharippu logo">
      <rect width="40" height="40" rx="10" fill="var(--logo-bg)" />
      <g fill="var(--amber)">
        <rect x="9" y="17" width="4" height="9" rx="2" /><rect x="15" y="10" width="4" height="16" rx="2" />
        <rect x="21" y="13" width="4" height="13" rx="2" /><rect x="27" y="19" width="4" height="7" rx="2" />
      </g>
      <path d="M7 31c3-3 6-3 9 0s6 3 9 0 6-3 8 0" stroke="var(--logo-wave)" strokeWidth="2.2" fill="none" strokeLinecap="round" />
    </svg>
  );
}
