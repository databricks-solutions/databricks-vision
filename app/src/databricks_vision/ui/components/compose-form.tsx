/**
 * ComposeForm — the Generate page's Compose mode: build a marketing creative (poster, social
 * post, banner) from role-tagged images — background, products, logo, style reference — plus
 * exact copy, a brand kit and a format. The parent streams POST /api/compose into its results.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import type { FolderOut, ImageModelOut, StyleGuidelineOut } from "@/lib/api";
import { useListFormatPresets } from "@/lib/api";
import { CHECKERBOARD_STYLE, DEFAULT_QUALITIES } from "@/lib/image-models";
import VolumeBrowserDialog from "@/components/apx/volume-browser-dialog";
import {
  COMPLEXITY_DEFAULT,
  ComplexitySelect,
  FormatChip,
  ModelSelect,
  QualitySelect,
} from "@/components/model-controls";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { FolderOpen, Layers, StopCircle, Upload, X } from "lucide-react";
import { toast } from "sonner";

// A reference image: a local upload or a UC Volume file picked in the volume browser.
export type Slot = { kind: "file"; file: File } | { kind: "volume"; path: string };

const MAX_PRODUCTS = 3;
const IMAGE_TYPES = "image/png,image/jpeg,image/webp";
const VOLUME_IMAGE_EXTS = [".png", ".jpg", ".jpeg", ".webp"];

function slotPreviewUrl(slot: Slot | null): string | null {
  if (!slot) return null;
  return slot.kind === "file"
    ? URL.createObjectURL(slot.file)
    : `/api/volumes/file?path=${encodeURIComponent(slot.path)}`;
}

function ImageSlot({
  label,
  hint,
  value,
  onChange,
  allowVolume = true,
}: {
  label: string;
  hint: string;
  value: Slot | null;
  onChange: (slot: Slot | null) => void;
  allowVolume?: boolean;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [browseOpen, setBrowseOpen] = useState(false);
  const preview = useMemo(() => slotPreviewUrl(value), [value]);

  useEffect(() => {
    return () => {
      if (preview?.startsWith("blob:")) URL.revokeObjectURL(preview);
    };
  }, [preview]);

  return (
    <div className="flex items-center gap-2">
      {preview ? (
        <img src={preview} alt={label} className="h-12 w-12 rounded border object-contain shrink-0" style={CHECKERBOARD_STYLE} />
      ) : (
        <div className="h-12 w-12 rounded border border-dashed shrink-0" />
      )}
      <div className="min-w-0 flex-1">
        <p className="text-xs font-medium">{label}</p>
        <p className="text-[10px] text-muted-foreground truncate">
          {value?.kind === "volume" ? value.path : value?.kind === "file" ? value.file.name : hint}
        </p>
      </div>
      <input
        ref={inputRef}
        type="file"
        accept={IMAGE_TYPES}
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) onChange({ kind: "file", file });
          e.target.value = "";
        }}
      />
      <Button type="button" variant="outline" size="icon" className="h-7 w-7" title="Upload" onClick={() => inputRef.current?.click()}>
        <Upload className="h-3.5 w-3.5" />
      </Button>
      {allowVolume && (
        <>
          <Button type="button" variant="outline" size="icon" className="h-7 w-7" title="Pick from a Volume" onClick={() => setBrowseOpen(true)}>
            <FolderOpen className="h-3.5 w-3.5" />
          </Button>
          <VolumeBrowserDialog
            open={browseOpen}
            onOpenChange={setBrowseOpen}
            onSelect={(path) => onChange({ kind: "volume", path })}
            mode="file"
            fileFilter={VOLUME_IMAGE_EXTS}
          />
        </>
      )}
      {value && (
        <Button type="button" variant="ghost" size="icon" className="h-7 w-7" title="Remove" onClick={() => onChange(null)}>
          <X className="h-3.5 w-3.5" />
        </Button>
      )}
    </div>
  );
}

function appendSlot(fd: FormData, slot: Slot | null, fileField: string, pathField: string) {
  if (!slot) return;
  if (slot.kind === "file") fd.append(fileField, slot.file);
  else fd.append(pathField, slot.path);
}

export function ComposeForm({
  imageModels,
  imageModelId,
  onImageModelChange,
  guidelines,
  folders,
  generating,
  onSubmit,
  onStop,
  initialProduct,
}: {
  imageModels: ImageModelOut[];
  imageModelId: string;
  onImageModelChange: (id: string) => void;
  guidelines: StyleGuidelineOut[];
  folders: FolderOut[];
  generating: boolean;
  onSubmit: (formData: FormData, count: number) => void;
  onStop: () => void;
  initialProduct: File | null;
}) {
  const { data: formatsData } = useListFormatPresets();
  const formats = formatsData?.data ?? [];

  const [background, setBackground] = useState<Slot | null>(null);
  const [products, setProducts] = useState<{ id: string; slot: Slot }[]>([]);
  const [logoOverride, setLogoOverride] = useState<Slot | null>(null);
  const [styleRef, setStyleRef] = useState<Slot | null>(null);
  const [kitId, setKitId] = useState("none");
  const [format, setFormat] = useState("square");
  const [headline, setHeadline] = useState("");
  const [subheadline, setSubheadline] = useState("");
  const [cta, setCta] = useState("");
  const [artDirection, setArtDirection] = useState("");
  const [quality, setQuality] = useState("auto");
  const [complexity, setComplexity] = useState(COMPLEXITY_DEFAULT);
  const [n, setN] = useState(1);
  const [folder, setFolder] = useState("default");

  // Pre-select the default brand kit once the list arrives.
  const kitInitedRef = useRef(false);
  useEffect(() => {
    if (kitInitedRef.current || guidelines.length === 0) return;
    kitInitedRef.current = true;
    const dflt = guidelines.find((g) => g.is_default);
    if (dflt) setKitId(String(dflt.id));
  }, [guidelines]);

  // "Use in Compose" from the gallery drops the image into the first product slot.
  useEffect(() => {
    if (initialProduct) setProducts([{ id: crypto.randomUUID(), slot: { kind: "file", file: initialProduct } }]);
  }, [initialProduct]);

  const model = imageModels.find((m) => m.id === imageModelId);
  const qualities = model?.qualities ?? DEFAULT_QUALITIES;
  useEffect(() => {
    if (!qualities.includes(quality)) setQuality("auto");
  }, [qualities, quality]);

  const kit = guidelines.find((g) => String(g.id) === kitId);
  const kitLogoUrl = kit?.logo_path
    ? `/api/style-guidelines/${kit.id}/logo?v=${encodeURIComponent(kit.updated_at ?? "")}`
    : null;
  const imageCount =
    (background ? 1 : 0) + products.length + (logoOverride || kitLogoUrl ? 1 : 0) + (styleRef ? 1 : 0);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (imageCount === 0) {
      toast.error("Add at least one image: a product, background, logo or style reference");
      return;
    }
    const fd = new FormData();
    fd.set("format", format);
    fd.set("headline", headline);
    fd.set("subheadline", subheadline);
    fd.set("cta", cta);
    fd.set("art_direction", artDirection);
    if (kit) fd.set("brand_kit_id", String(kit.id));
    appendSlot(fd, background, "background", "background_path");
    for (const p of products) appendSlot(fd, p.slot, "products", "product_paths");
    if (logoOverride?.kind === "file") fd.set("logo", logoOverride.file);
    appendSlot(fd, styleRef, "style_ref", "style_ref_path");
    fd.set("n", String(n));
    fd.set("folder", folder);
    fd.set("quality", quality);
    if (imageModelId) fd.set("image_model", imageModelId);
    if (model?.supports_complexity && complexity !== COMPLEXITY_DEFAULT) fd.set("complexity", complexity);
    onSubmit(fd, n);
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="space-y-2">
        <Label>Format</Label>
        <div className="flex flex-wrap gap-1.5">
          {formats.map((p) => (
            <FormatChip key={p.key} preset={p} selected={format === p.key} onClick={() => setFormat(p.key)} />
          ))}
        </div>
      </div>

      <div className="space-y-2">
        <Label>Brand kit</Label>
        <Select value={kitId} onValueChange={(v) => { setKitId(v); setLogoOverride(null); }}>
          <SelectTrigger className="h-8 text-xs">
            {/* Label rendered directly — the kit list loads async (see the style-guideline select). */}
            <span>{kit ? kit.name : "None"}</span>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="none" className="text-xs">None</SelectItem>
            {guidelines.map((g) => (
              <SelectItem key={g.id} value={String(g.id)} className="text-xs">
                {g.name}{g.is_default ? " · default" : ""}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {kit && ((kit.palette ?? []).length > 0 || kit.typography) && (
          <div className="flex items-center gap-1.5">
            {(kit.palette ?? []).map((colour) => (
              <span key={colour} title={colour} className="h-4 w-4 rounded-full border" style={{ backgroundColor: colour }} />
            ))}
            {kit.typography && <span className="text-[10px] text-muted-foreground truncate ml-1">{kit.typography}</span>}
          </div>
        )}
      </div>

      <div className="space-y-2.5">
        <Label>Images</Label>
        <ImageSlot label="Background" hint="Optional scene / backdrop" value={background} onChange={setBackground} />
        {products.map((p, i) => (
          <ImageSlot
            key={p.id}
            label={`Product ${i + 1}`}
            hint="Reproduced exactly"
            value={p.slot}
            onChange={(next) =>
              setProducts((prev) =>
                next ? prev.map((q) => (q.id === p.id ? { ...q, slot: next } : q)) : prev.filter((q) => q.id !== p.id),
              )
            }
          />
        ))}
        {products.length < MAX_PRODUCTS && (
          <ImageSlot
            label={products.length === 0 ? "Product" : "Add another product"}
            hint="Shot or packshot — reproduced exactly"
            value={null}
            onChange={(next) => next && setProducts((prev) => [...prev, { id: crypto.randomUUID(), slot: next }])}
          />
        )}
        {kitLogoUrl && !logoOverride ? (
          <div className="flex items-center gap-2">
            <img src={kitLogoUrl} alt={`${kit?.name} logo`} className="h-12 w-12 rounded border object-contain shrink-0" style={CHECKERBOARD_STYLE} />
            <div className="min-w-0 flex-1">
              <p className="text-xs font-medium">Logo</p>
              <p className="text-[10px] text-muted-foreground">From brand kit "{kit?.name}"</p>
            </div>
          </div>
        ) : (
          <ImageSlot
            label="Logo"
            hint={kitLogoUrl ? "Overrides the brand kit logo" : "Placed unaltered"}
            value={logoOverride}
            onChange={setLogoOverride}
            allowVolume={false}
          />
        )}
        <ImageSlot label="Style reference" hint="Lighting / colour grading only" value={styleRef} onChange={setStyleRef} />
      </div>

      <div className="space-y-2">
        <Label>Copy <span className="text-muted-foreground text-xs font-normal">(rendered exactly)</span></Label>
        <Input value={headline} onChange={(e) => setHeadline(e.target.value)} placeholder="Headline" />
        <Input value={subheadline} onChange={(e) => setSubheadline(e.target.value)} placeholder="Subheadline (optional)" />
        <Input value={cta} onChange={(e) => setCta(e.target.value)} placeholder="Call to action, e.g. Shop now (optional)" />
      </div>

      <div className="space-y-2">
        <Label>Art direction <span className="text-muted-foreground text-xs font-normal">(optional)</span></Label>
        <Textarea
          value={artDirection}
          onChange={(e) => setArtDirection(e.target.value)}
          rows={2}
          placeholder="e.g. Sunlit beach at golden hour, product on a driftwood plinth"
          className="resize-y text-xs"
        />
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div className="space-y-1 col-span-2">
          <Label className="text-xs">Model</Label>
          <ModelSelect models={imageModels} value={imageModelId} onChange={onImageModelChange} />
        </div>
        <div className="space-y-1">
          <Label className="text-xs">Quality</Label>
          <QualitySelect qualities={qualities} value={quality} onChange={setQuality} />
        </div>
        <div className="space-y-1">
          <Label className="text-xs">Count</Label>
          <Select value={String(n)} onValueChange={(v) => setN(Number(v))}>
            <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>{[1, 2, 3, 4].map((i) => (<SelectItem key={i} value={String(i)}>{i}</SelectItem>))}</SelectContent>
          </Select>
        </div>
        {model?.supports_complexity && (
          <div className="space-y-1 col-span-2">
            <Label className="text-xs">Complexity</Label>
            <ComplexitySelect value={complexity} onChange={setComplexity} defaultLabel="Auto (high for layouts)" />
          </div>
        )}
      </div>

      <div className="space-y-2">
        <Label>Save to folder</Label>
        <Select value={folder} onValueChange={setFolder}>
          <SelectTrigger><SelectValue /></SelectTrigger>
          <SelectContent>
            {folders.map((f) => (<SelectItem key={f.name} value={f.name}>{f.name}</SelectItem>))}
            {folders.length === 0 && <SelectItem value="default">default</SelectItem>}
          </SelectContent>
        </Select>
      </div>

      <div className="flex gap-2 pt-1">
        <Button type="submit" className="flex-1" disabled={generating}>
          <Layers className="h-4 w-4 mr-2" />
          {generating ? "Composing..." : "Compose"}
        </Button>
        {generating && (
          <Button type="button" variant="outline" size="icon" onClick={onStop}><StopCircle className="h-4 w-4" /></Button>
        )}
      </div>
    </form>
  );
}
