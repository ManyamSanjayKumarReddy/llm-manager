/** The GPUs in this machine. (Change this list if the GPU box has a different number.) */
const MACHINE_GPUS = [0, 1];

/** Toggle buttons for the GPUs a model occupies while awake. */
export function GpuPicker({ value, onChange }: { value: number[]; onChange: (gpus: number[]) => void }) {
  // A model registered earlier may use a GPU outside this list: keep showing it so it can be changed.
  const all = [...new Set([...MACHINE_GPUS, ...value])].sort((a, b) => a - b);
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
