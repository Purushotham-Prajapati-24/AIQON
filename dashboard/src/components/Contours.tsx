import { motion, useMotionValue, useReducedMotion, useSpring, useTransform } from "motion/react";
import { useEffect, useMemo } from "react";

/** Depth contours from a nautical chart: the hero's texture. Drifts gently with the pointer. */
export function Contours() {
  const reduce = useReducedMotion();
  const mx = useMotionValue(0);
  const my = useMotionValue(0);
  const sx = useSpring(mx, { stiffness: 40, damping: 20 });
  const sy = useSpring(my, { stiffness: 40, damping: 20 });
  const x1 = useTransform(sx, (v) => v * 14);
  const y1 = useTransform(sy, (v) => v * 10);
  const x2 = useTransform(sx, (v) => v * -22);
  const y2 = useTransform(sy, (v) => v * -14);

  useEffect(() => {
    if (reduce) return;
    const on = (e: PointerEvent) => {
      mx.set(e.clientX / innerWidth - 0.5);
      my.set(e.clientY / innerHeight - 0.5);
    };
    addEventListener("pointermove", on, { passive: true });
    return () => removeEventListener("pointermove", on);
  }, [mx, my, reduce]);

  const [near, far] = useMemo(() => [lines(14, 1.7, 0), lines(10, 2.6, 2)], []);

  return (
    <div aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden">
      <motion.svg style={{ x: x2, y: y2 }} className="absolute -inset-[6%] h-[112%] w-[112%]" viewBox="0 0 1600 1000" preserveAspectRatio="none">
        {far.map((d, i) => (
          <path key={i} d={d} fill="none" stroke="var(--contour)" strokeWidth={1} />
        ))}
      </motion.svg>
      <motion.svg style={{ x: x1, y: y1 }} className="absolute -inset-[4%] h-[108%] w-[108%]" viewBox="0 0 1600 1000" preserveAspectRatio="none">
        {near.map((d, i) => (
          <path key={i} d={d} fill="none" stroke="var(--contour)" strokeWidth={1.2} strokeDasharray={i % 3 === 0 ? "2 6" : undefined} />
        ))}
      </motion.svg>
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_70%_20%,transparent_0%,var(--bg)_75%)]" />
    </div>
  );
}

/** Deterministic wavy isolines (sum of sines), like soundings on a sea chart. */
function lines(n: number, freq: number, phase: number) {
  const out: string[] = [];
  for (let k = 0; k < n; k++) {
    const base = 80 + (k * 900) / n;
    let d = "";
    for (let x = -20; x <= 1620; x += 20) {
      const t = x / 1600;
      const y =
        base +
        38 * Math.sin(t * Math.PI * freq + k * 0.55 + phase) +
        18 * Math.sin(t * Math.PI * freq * 2.3 + k * 1.3) +
        9 * Math.cos(t * Math.PI * 5.1 + k);
      d += `${x === -20 ? "M" : "L"}${x},${y.toFixed(1)}`;
    }
    out.push(d);
  }
  return out;
}
