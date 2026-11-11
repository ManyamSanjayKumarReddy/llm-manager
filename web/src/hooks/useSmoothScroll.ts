import Lenis from "lenis";
import { useEffect } from "react";

/** Inertial smooth scrolling for the whole page (skipped for people who prefer less motion). */
export function useSmoothScroll(): void {
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return undefined;
    const lenis = new Lenis({ lerp: 0.1, wheelMultiplier: 1, anchors: true });
    let frame = requestAnimationFrame(function tick(time) {
      lenis.raf(time);
      frame = requestAnimationFrame(tick);
    });
    return () => {
      cancelAnimationFrame(frame);
      lenis.destroy();
    };
  }, []);
}
