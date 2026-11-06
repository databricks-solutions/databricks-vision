/**
 * Shared generation controls used by the Generate page, the Compose form and Adapt.
 */
import type { FormatPresetOut, ImageModelOut } from "@/lib/api";
import { QUALITY_LABELS } from "@/lib/image-models";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

export const COMPLEXITY_DEFAULT = "default"; // Radix Select items can't use "" as a value

export function ModelSelect({
  models,
  value,
  onChange,
}: {
  models: ImageModelOut[];
  value: string;
  onChange: (v: string) => void;
}) {
  const selected = models.find((m) => m.id === value);
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger className="h-8 text-xs">
        {/* Label rendered directly — the model list loads async (see the style-guideline select). */}
        <span>{selected?.label ?? (value || "Loading…")}</span>
      </SelectTrigger>
      <SelectContent>
        {models.map((m) => (
          <SelectItem key={m.id} value={m.id} className="text-xs">
            {m.label} <span className="text-muted-foreground">· {m.description}</span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

export function QualitySelect({
  qualities,
  value,
  onChange,
}: {
  qualities: string[];
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger className="h-8 text-xs"><span>{QUALITY_LABELS[value] ?? value}</span></SelectTrigger>
      <SelectContent>
        {qualities.map((q) => (
          <SelectItem key={q} value={q}>{QUALITY_LABELS[q] ?? q}</SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

// A marketing-format toggle (image_gen.FORMAT_PRESETS), drawn as a chip whose outline has
// the format's aspect ratio.
export function FormatChip({
  preset,
  selected,
  onClick,
}: {
  preset: FormatPresetOut;
  selected: boolean;
  onClick: () => void;
}) {
  const [w, h] = preset.size.split("x").map(Number);
  const scale = 16 / Math.max(w, h);
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={selected}
      className={`flex items-center gap-2 rounded-md border px-2 py-1.5 text-xs transition-colors ${
        selected ? "border-primary bg-primary/10 text-foreground" : "text-muted-foreground hover:text-foreground hover:border-foreground/30"
      }`}
    >
      <span
        className={`inline-block border-2 rounded-[2px] ${selected ? "border-primary" : "border-current"}`}
        style={{ width: Math.round(w * scale), height: Math.round(h * scale) }}
      />
      <span className="font-medium">{preset.label}</span>
      <span className="text-[10px] opacity-70">{preset.ratio}</span>
    </button>
  );
}

export function ComplexitySelect({
  value,
  onChange,
  defaultLabel = "Model default",
}: {
  value: string;
  onChange: (v: string) => void;
  defaultLabel?: string;
}) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
      <SelectContent>
        <SelectItem value={COMPLEXITY_DEFAULT}>{defaultLabel}</SelectItem>
        <SelectItem value="low">Low — quick edits</SelectItem>
        <SelectItem value="medium">Medium</SelectItem>
        <SelectItem value="high">High — many elements or constraints</SelectItem>
      </SelectContent>
    </Select>
  );
}
