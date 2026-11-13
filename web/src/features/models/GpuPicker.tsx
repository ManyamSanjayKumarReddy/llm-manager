/** Toggle buttons for the GPUs a model occupies while awake, on a server that has ``count`` GPUs. */
export function GpuPicker({ count, value, onChange }: { count: number; value: number[]; onChange: (gpus: number[]) => void }) {
  // Keep showing a GPU a model already uses even if it is outside the server's range, so it can be fixed.
  const all = [...new Set([...Array.from({ length: count }, (_, i) => i), ...value])].sort((a, b) => a - b);
  return (
    <div className="chips" role="group" aria-label="GPUs">
      {all.map((gpu) => (
        <label key={gpu} className="chip-check">
          <input
            type="checkbox"
            checked={value.includes(gpu)}
            onChange={(e) => {
              onChange(e.target.checked ? [...value, gpu].sort((a, b) => a - b) : value.filter((g) => g !== gpu));
            }}
          />
          <span>GPU {gpu}</span>
        </label>
      ))}
    </div>
  );
}
