import { motion } from "motion/react";

const EASE = [0.16, 1, 0.3, 1] as const;

/** Half-ring meter for a probability. The number carries the value; the arc is the glance. */
export function Gauge({ value, color, size = 168 }: { value: number; color: string; size?: number }) {
  const r = size / 2 - 10;
  const c = Math.PI * r;
  return (
    <svg width={size} height={size / 2 + 8} viewBox={`0 0 ${size} ${size / 2 + 8}`} aria-hidden className="overflow-visible">
      <path
        d={`M10,${size / 2} A${r},${r} 0 0 1 ${size - 10},${size / 2}`}
        fill="none"
        stroke="var(--bg-3)"
        strokeWidth={10}
        strokeLinecap="round"
      />
      <motion.path
        d={`M10,${size / 2} A${r},${r} 0 0 1 ${size - 10},${size / 2}`}
        fill="none"
        stroke={color}
        strokeWidth={10}
        strokeLinecap="round"
        strokeDasharray={c}
        initial={{ strokeDashoffset: c }}
        animate={{ strokeDashoffset: c * (1 - Math.max(0.01, Math.min(1, value))) }}
        transition={{ duration: 1.1, ease: EASE }}
      />
    </svg>
  );
}
