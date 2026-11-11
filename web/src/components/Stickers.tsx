import {
  CatSitSticker,
  CosmicEyeSticker,
  CosmicPillSticker,
  MetalSticker,
  PipRocketSticker,
  PipThinkingSticker,
  SparkleTrioSticker,
  StarBurstSticker,
} from "stick-it-up";

const PICK = {
  metal: MetalSticker,
  pill: CosmicPillSticker,
  star: StarBurstSticker,
  rocket: PipRocketSticker,
  thinking: PipThinkingSticker,
  sparkles: SparkleTrioSticker,
  eye: CosmicEyeSticker,
  nap: CatSitSticker,
} as const;

export type StickerName = keyof typeof PICK;

/** A decorative sticker that floats gently and peels at a corner on hover. */
export function Deco({ name, size = 110, delay = 0, rotate = 0, className = "" }: { name: StickerName; size?: number; delay?: number; rotate?: number; className?: string }) {
  const Component = PICK[name];
  return (
    <span className={`sticker ${className}`} style={{ "--d": `${delay}s`, "--r": `${rotate}deg`, transform: `rotate(${rotate}deg)` } as React.CSSProperties} aria-hidden="true">
      <Component size={size} peel />
    </span>
  );
}
