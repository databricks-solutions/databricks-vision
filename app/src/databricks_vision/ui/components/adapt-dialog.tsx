/**
 * AdaptDialog — pick the marketing formats to re-lay out a finished creative into.
 * The Generate page runs the adaptation (POST /api/adapt) and streams the results.
 */
import { useEffect, useState } from "react";
import { useListFormatPresets } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
} from "@/components/ui/dialog";
import { FormatChip } from "@/components/model-controls";
import { Crop } from "lucide-react";

export type AdaptSource =
  // A fresh result on the Generate page (sent to the backend as an upload).
  | { kind: "result"; b64: string; mime: string }
  // A saved gallery image (the backend reads it by id).
  | { kind: "gallery"; batchId: string; imageId: number; previewUrl: string; folder: string | null };

export function AdaptDialog({
  source,
  open,
  onOpenChange,
  onAdapt,
}: {
  source: AdaptSource | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onAdapt: (formats: string[]) => void;
}) {
  const { data } = useListFormatPresets();
  const presets = data?.data ?? [];
  const [picked, setPicked] = useState<string[]>([]);

  useEffect(() => {
    if (open) setPicked([]);
  }, [open]);

  const preview =
    source?.kind === "result" ? `data:${source.mime};base64,${source.b64}` : source?.previewUrl;
  const toggle = (key: string) =>
    setPicked((p) => (p.includes(key) ? p.filter((k) => k !== key) : [...p, key]));
  // Submit in catalogue order so result cards line up with the chips.
  const ordered = presets.filter((p) => picked.includes(p.key)).map((p) => p.key);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogTitle>Adapt to formats</DialogTitle>
        <DialogDescription>
          Re-lays out this creative for each format you pick. Text, logo, product and colours stay
          the same; the background is extended or recomposed to fit.
        </DialogDescription>
        <div className="flex gap-4 py-2">
          {preview && (
            <img
              src={preview}
              alt="Source creative"
              className="w-28 h-28 object-contain rounded border bg-muted shrink-0"
            />
          )}
          <div className="flex flex-wrap gap-2 content-start">
            {presets.map((p) => (
              <FormatChip key={p.key} preset={p} selected={picked.includes(p.key)} onClick={() => toggle(p.key)} />
            ))}
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button disabled={ordered.length === 0} onClick={() => onAdapt(ordered)}>
            <Crop className="h-4 w-4 mr-2" />
            {ordered.length > 0
              ? `Adapt to ${ordered.length} format${ordered.length > 1 ? "s" : ""}`
              : "Adapt"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
