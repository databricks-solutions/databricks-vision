/**
 * BrandKitSelect — the one brand kit picker on the Generate page (Single, Edit, Batch, Compose).
 * A kit does two jobs, so the picker says which ones apply where: Compose puts the kit's logo,
 * colours and typography into the creative, and in every mode the judges score the result
 * against the kit's rules (its `body`, sent as `criteria`).
 */
import { Link } from "@tanstack/react-router";
import type { StyleGuidelineOut } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger } from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { ClipboardCheck, Sparkles } from "lucide-react";

export const NO_KIT = "none"; // Radix Select items can't use "" as a value

export type BrandKitScope = "generate" | "batch" | "compose";

// Captions are sized to fit one line in the Generate sidebar (~368px at text-[10px]).
const SCOPES: Record<BrandKitScope, { generation: boolean; caption: string }> = {
  generate: {
    generation: false,
    caption: "Judges check the image against the kit's rules. Generation is unchanged.",
  },
  batch: {
    generation: false,
    caption: "Judges check the kit's rules on Analyze Images. Generation is unchanged.",
  },
  compose: {
    generation: true,
    caption: "Logo, colours and type shape the creative; judges check the kit's rules.",
  },
};

export function kitLabel(kit: StyleGuidelineOut): string {
  return `${kit.name}${kit.is_default ? " · default" : ""}`;
}

// Sparkles = shapes generation, ClipboardCheck = scored by the judges (also used in Settings).
export function ScopeChip({ icon: Icon, children }: { icon: typeof Sparkles; children: string }) {
  return (
    <Badge variant="outline" className="gap-1 px-1.5 py-0 text-[10px] font-medium text-muted-foreground">
      <Icon className="h-2.5 w-2.5" />
      {children}
    </Badge>
  );
}

export function BrandKitSelect({
  kits,
  value,
  onChange,
  scope,
  className,
  labelClassName,
}: {
  kits: StyleGuidelineOut[];
  value: string;
  onChange: (id: string) => void;
  scope: BrandKitScope;
  className?: string;
  labelClassName?: string;
}) {
  const selected = kits.find((k) => String(k.id) === value);
  const { generation, caption } = SCOPES[scope];
  return (
    <div className={cn("space-y-1", className)}>
      <div className="flex items-center gap-1.5">
        <Label className={labelClassName}>Brand kit</Label>
        {generation && <ScopeChip icon={Sparkles}>Generation</ScopeChip>}
        <ScopeChip icon={ClipboardCheck}>Scoring</ScopeChip>
      </div>
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger className="h-8 text-xs">
          {/* Custom trigger label — Radix's SelectValue derives text from a registered
              SelectItemText, which only mounts after the dropdown first opens, and the kit list
              loads async. Rendering the label directly avoids a blank trigger. */}
          <span>{selected ? kitLabel(selected) : "None"}</span>
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={NO_KIT} className="text-xs">None</SelectItem>
          {kits.map((k) => (
            <SelectItem key={k.id} value={String(k.id)} className="text-xs">
              {kitLabel(k)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <p className="text-[10px] leading-snug text-muted-foreground">{caption}</p>
      {kits.length === 0 && (
        <p className="text-[10px] text-muted-foreground">
          No brand kits yet. Create one in <Link to="/settings" className="underline hover:text-foreground">Settings</Link>.
        </p>
      )}
    </div>
  );
}
