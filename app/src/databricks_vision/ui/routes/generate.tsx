import { createFileRoute, Link } from "@tanstack/react-router";
import { useState, useRef, useCallback, useEffect } from "react";
import Navbar from "@/components/apx/navbar";
import { BatchDetailContent } from "@/components/batch-detail";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { streamSSE } from "@/lib/sse";
import { useQueryClient } from "@tanstack/react-query";
import { useCreateBatch, useListFolders, useListStyleGuidelines, listBatchesKey } from "@/lib/api";
import VolumeBrowserDialog from "@/components/apx/volume-browser-dialog";
import { Sparkles, X, Upload, ImagePlus, StopCircle, FolderOpen, Plus } from "lucide-react";
import { toast } from "sonner";

export const Route = createFileRoute("/generate")({
  component: GeneratePage,
});

type GeneratedImage = {
  index: number;
  b64: string;
  done: boolean;
  partialCount: number;
};

type VariationRow = { label: string; prompt: string; edited: boolean };

// Batch keeps a small fixed list — flexible/custom sizes are single + edit only for now.
const SIZE_PRESETS: { value: string; label: string }[] = [
  { value: "1024x1024", label: "Square (1024)" },
  { value: "1536x1024", label: "Landscape (1536×1024)" },
  { value: "1024x1536", label: "Portrait (1024×1536)" },
  { value: "2048x1152", label: "Wide (2048×1152)" },
  { value: "2048x2048", label: "Large Square (2048)" },
];

function SizeSelect({ value, onChange, className = "" }: { value: string; onChange: (v: string) => void; className?: string }) {
  return (
    <div className={`space-y-1 ${className}`}>
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
        <SelectContent>
          {SIZE_PRESETS.map((p) => (
            <SelectItem key={p.value} value={p.value}>{p.label}</SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

// gpt-image-2 size catalogue + custom validation. Mirrors backend
// _validate_size in routers/generate.py.
type GptImage2PresetGroup = "1K" | "2K" | "4K";
type GptImage2Preset = { value: string; label: string; group?: GptImage2PresetGroup };

const GPT_IMAGE_2_PRESETS: GptImage2Preset[] = [
  { value: "auto", label: "Auto" },
  { value: "1024x1024", label: "Square (1024)", group: "1K" },
  { value: "1536x1024", label: "Landscape (1536×1024)", group: "1K" },
  { value: "1024x1536", label: "Portrait (1024×1536)", group: "1K" },
  { value: "2048x2048", label: "2K Square (2048)", group: "2K" },
  { value: "2048x1152", label: "2K Landscape (2048×1152)", group: "2K" },
  { value: "3840x2160", label: "4K Landscape (3840×2160)", group: "4K" },
  { value: "2160x3840", label: "4K Portrait (2160×3840)", group: "4K" },
];

const GPT_IMAGE_15_VALUES = new Set(["auto", "1024x1024", "1024x1536", "1536x1024"]);
const SIZE_CUSTOM_SENTINEL = "__custom__";

function parseSize(s: string): [number, number] | null {
  const m = s.match(/^(\d+)x(\d+)$/);
  return m ? [parseInt(m[1], 10), parseInt(m[2], 10)] : null;
}

function validateGptImage2Size(w: number, h: number): string | null {
  if (!Number.isFinite(w) || !Number.isFinite(h)) return "Width and height required";
  if (!Number.isInteger(w) || !Number.isInteger(h)) return "Whole numbers only";
  if (w <= 0 || h <= 0) return "Must be positive";
  if (w % 16 !== 0 || h % 16 !== 0) return "Both dimensions must be multiples of 16";
  if (Math.max(w, h) > 3840) return "Max edge is 3840px";
  const pixels = w * h;
  if (pixels < 655_360) return `Min 655,360 pixels (current: ${pixels.toLocaleString()})`;
  if (pixels > 8_294_400) return `Max 8,294,400 pixels (current: ${pixels.toLocaleString()})`;
  const ratio = Math.max(w, h) / Math.min(w, h);
  if (ratio > 3.0) return `Ratio ≤ 3:1 (current: ${ratio.toFixed(2)})`;
  return null;
}

// Picks the closest gpt-image-1.5 size to fall back to when transparent BG is enabled
// and the current size isn't supported by gpt-image-1.5.
function snapToTransparentSize(value: string): string {
  if (GPT_IMAGE_15_VALUES.has(value)) return value;
  const parsed = parseSize(value);
  if (!parsed) return "1024x1024";
  const [w, h] = parsed;
  if (w === h) return "1024x1024";
  return w > h ? "1536x1024" : "1024x1536";
}

function SizeSelectAdvanced({
  value,
  onChange,
  transparent,
  onValidityChange,
}: {
  value: string;
  onChange: (v: string) => void;
  transparent: boolean;
  onValidityChange: (valid: boolean) => void;
}) {
  const isPresetValue = (v: string) => GPT_IMAGE_2_PRESETS.some((p) => p.value === v);
  const initialParse = parseSize(value);
  const [customMode, setCustomMode] = useState(() => !isPresetValue(value));
  const [customW, setCustomW] = useState(initialParse?.[0] ?? 1024);
  const [customH, setCustomH] = useState(initialParse?.[1] ?? 1024);

  // Transparent BG forces gpt-image-1.5 — exit custom mode (parent will snap value).
  useEffect(() => {
    if (transparent) setCustomMode(false);
  }, [transparent]);

  const customError = customMode ? validateGptImage2Size(customW, customH) : null;
  const valid = !customMode || customError === null;

  useEffect(() => {
    onValidityChange(valid);
  }, [valid, onValidityChange]);

  // Push valid custom dimensions up to the parent.
  useEffect(() => {
    if (customMode && customError === null) {
      const v = `${customW}x${customH}`;
      if (v !== value) onChange(v);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [customMode, customW, customH, customError]);

  const handleSelect = (v: string) => {
    if (v === SIZE_CUSTOM_SENTINEL) {
      const parsed = parseSize(value);
      if (parsed) {
        setCustomW(parsed[0]);
        setCustomH(parsed[1]);
      }
      setCustomMode(true);
    } else {
      setCustomMode(false);
      onChange(v);
    }
  };

  const triggerValue = customMode ? SIZE_CUSTOM_SENTINEL : value;
  const filterPreset = (p: GptImage2Preset) => !transparent || GPT_IMAGE_15_VALUES.has(p.value);
  const auto = GPT_IMAGE_2_PRESETS.filter((p) => p.group === undefined && filterPreset(p));
  const oneK = GPT_IMAGE_2_PRESETS.filter((p) => p.group === "1K" && filterPreset(p));
  const twoK = GPT_IMAGE_2_PRESETS.filter((p) => p.group === "2K" && filterPreset(p));
  const fourK = GPT_IMAGE_2_PRESETS.filter((p) => p.group === "4K" && filterPreset(p));

  return (
    <div className="space-y-1">
      <Select value={triggerValue} onValueChange={handleSelect}>
        <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
        <SelectContent>
          {auto.length > 0 && (
            <SelectGroup>
              {auto.map((p) => (
                <SelectItem key={p.value} value={p.value} className="text-xs">{p.label}</SelectItem>
              ))}
            </SelectGroup>
          )}
          {oneK.length > 0 && (
            <SelectGroup>
              <SelectSeparator />
              <SelectLabel className="text-[10px] uppercase tracking-wider text-muted-foreground">1K</SelectLabel>
              {oneK.map((p) => (
                <SelectItem key={p.value} value={p.value} className="text-xs">{p.label}</SelectItem>
              ))}
            </SelectGroup>
          )}
          {twoK.length > 0 && (
            <SelectGroup>
              <SelectSeparator />
              <SelectLabel className="text-[10px] uppercase tracking-wider text-muted-foreground">2K</SelectLabel>
              {twoK.map((p) => (
                <SelectItem key={p.value} value={p.value} className="text-xs">{p.label}</SelectItem>
              ))}
            </SelectGroup>
          )}
          {fourK.length > 0 && (
            <SelectGroup>
              <SelectSeparator />
              <SelectLabel className="text-[10px] uppercase tracking-wider text-muted-foreground">4K</SelectLabel>
              {fourK.map((p) => (
                <SelectItem key={p.value} value={p.value} className="text-xs">{p.label}</SelectItem>
              ))}
            </SelectGroup>
          )}
          {!transparent && (
            <SelectGroup>
              <SelectSeparator />
              <SelectItem value={SIZE_CUSTOM_SENTINEL} className="text-xs">Custom…</SelectItem>
            </SelectGroup>
          )}
        </SelectContent>
      </Select>
      {customMode && (
        <div className="space-y-1 pt-1">
          <div className="flex items-center gap-1.5 text-xs">
            <input
              type="number"
              value={customW}
              onChange={(e) => setCustomW(parseInt(e.target.value, 10) || 0)}
              onBlur={(e) => {
                const v = parseInt(e.target.value, 10) || 0;
                setCustomW(Math.round(v / 16) * 16);
              }}
              min={16}
              max={3840}
              step={16}
              className="w-20 h-7 px-2 rounded-md border bg-background text-xs"
              aria-label="Width"
            />
            <span className="text-muted-foreground">×</span>
            <input
              type="number"
              value={customH}
              onChange={(e) => setCustomH(parseInt(e.target.value, 10) || 0)}
              onBlur={(e) => {
                const v = parseInt(e.target.value, 10) || 0;
                setCustomH(Math.round(v / 16) * 16);
              }}
              min={16}
              max={3840}
              step={16}
              className="w-20 h-7 px-2 rounded-md border bg-background text-xs"
              aria-label="Height"
            />
            <span className="text-muted-foreground text-[10px]">px (multiples of 16)</span>
          </div>
          {customError && (
            <p className="text-[10px] text-red-600 dark:text-red-400">{customError}</p>
          )}
        </div>
      )}
    </div>
  );
}

function GeneratePage() {
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<"single" | "edit" | "batch">("single");

  // Folders
  const { data: foldersData } = useListFolders();
  const folders = foldersData?.data ?? [];

  // Style guidelines (managed in /settings)
  const { data: guidelinesData } = useListStyleGuidelines();
  const guidelines = guidelinesData?.data ?? [];

  // Pick up pre-loaded image from ImageDialog "Edit" button
  useEffect(() => {
    const blobUrl = sessionStorage.getItem("edit-image-blob-url");
    const filename = sessionStorage.getItem("edit-image-filename");
    const editPrompt = sessionStorage.getItem("edit-image-prompt");
    const srcBatchId = sessionStorage.getItem("edit-source-batch-id");
    const srcImageId = sessionStorage.getItem("edit-source-image-id");
    const srcFolder = sessionStorage.getItem("edit-source-folder");
    if (blobUrl) {
      const refBlobUrl = sessionStorage.getItem("edit-ref-blob-url");
      const refFilename = sessionStorage.getItem("edit-ref-filename");
      const inputBlobUrl = sessionStorage.getItem("edit-input-blob-url");
      const inputFilename = sessionStorage.getItem("edit-input-filename");
      // Clean up all sessionStorage
      for (const key of ["edit-image-blob-url", "edit-image-filename", "edit-image-prompt",
        "edit-source-batch-id", "edit-source-image-id", "edit-source-folder",
        "edit-ref-blob-url", "edit-ref-filename",
        "edit-input-blob-url", "edit-input-filename"]) {
        sessionStorage.removeItem(key);
      }
      // Store source context (kept for analytics; backend no longer reads it).
      if (srcBatchId && srcImageId) {
        setSourceBatchId(srcBatchId);
        setSourceImageId(Number(srcImageId));
      }
      // Default the destination folder to the source's folder so edits stay grouped.
      if (srcFolder) setFolder(srcFolder);
      // Fetch all images in parallel and pre-load into edit mode
      const fetchFile = async (url: string, name: string): Promise<File> => {
        const r = await fetch(url);
        const b = await r.blob();
        return new File([b], name, { type: b.type || "image/png" });
      };
      Promise.all([
        fetchFile(blobUrl, filename ?? "image.png"),
        refBlobUrl ? fetchFile(refBlobUrl, refFilename ?? "reference.png") : null,
        inputBlobUrl ? fetchFile(inputBlobUrl, inputFilename ?? "input.png") : null,
      ].filter(Boolean) as Promise<File>[])
        .then((files) => {
          setMode("edit");
          setUploadedImages(files);
          if (editPrompt) setPrompt(editPrompt);
        })
        .catch(() => {});
    }
  }, []);

  // --- Source context (when editing an existing image) ---
  const [sourceBatchId, setSourceBatchId] = useState<string | null>(null);
  const [sourceImageId, setSourceImageId] = useState<number | null>(null);

  // --- Single / Edit state ---
  const [prompt, setPrompt] = useState("");
  const [originalPrompt, setOriginalPrompt] = useState<string | null>(null);
  const [enhancing, setEnhancing] = useState(false);
  const [quality, setQuality] = useState("auto");
  const [size, setSize] = useState("auto");
  const [sizeValid, setSizeValid] = useState(true);
  const [outputFormat, setOutputFormat] = useState("png");
  const [folder, setFolder] = useState("default");
  const [transparent, setTransparent] = useState(false);

  const handleTransparentToggle = useCallback((checked: boolean) => {
    setTransparent(checked);
    if (checked && !GPT_IMAGE_15_VALUES.has(size)) {
      const snapped = snapToTransparentSize(size);
      setSize(snapped);
      const label = GPT_IMAGE_2_PRESETS.find((p) => p.value === snapped)?.label ?? snapped;
      toast.info(`Switched size to ${label} — transparent BG uses gpt-image-1.5`);
    }
  }, [size]);
  // Apply the DB-marked default the first time the guidelines list arrives.
  // After that the value is whatever the user has explicitly chosen.
  const [styleGuidelineId, setStyleGuidelineId] = useState<string>("none");
  const styleGuidelineInitedRef = useRef(false);
  useEffect(() => {
    if (styleGuidelineInitedRef.current) return;
    if (guidelines.length === 0) return; // wait until React Query has data
    styleGuidelineInitedRef.current = true;
    const dflt = guidelines.find((g) => g.is_default);
    if (dflt) setStyleGuidelineId(String(dflt.id));
  }, [guidelines]);
  const [n, setN] = useState(1);
  const [uploadedImages, setUploadedImages] = useState<File[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [generating, setGenerating] = useState(false);
  const [analyzingImages, setAnalyzingImages] = useState(false);
  const [images, setImages] = useState<GeneratedImage[]>([]);
  const stopRef = useRef<(() => void) | null>(null);

  // --- Batch state ---
  const batchMutation = useCreateBatch();
  const [batchMode, setBatchMode] = useState<"multi_image" | "variations">("multi_image");
  const [batchName, setBatchName] = useState("");
  const [inputPath, setInputPath] = useState("");
  const [batchPrompt, setBatchPrompt] = useState("");
  const [refPath, setRefPath] = useState("");
  const [sourceImagePath, setSourceImagePath] = useState("");
  const [basePrompt, setBasePrompt] = useState("");
  const [enhancingBatch, setEnhancingBatch] = useState(false);
  const [batchSize, setBatchSize] = useState("1024x1024");
  const [batchSizeValid, setBatchSizeValid] = useState(true);
  const [batchQuality, setBatchQuality] = useState("auto");
  const [batchOutputFormat, setBatchOutputFormat] = useState("png");
  const [batchTransparent, setBatchTransparent] = useState(false);
  const [batchStyleGuidelineId, setBatchStyleGuidelineId] = useState<string>("none");

  // Transparent BG forces gpt-image-1.5 + snaps to a supported size, mirroring single-gen.
  const handleBatchTransparentToggle = useCallback((checked: boolean) => {
    setBatchTransparent(checked);
    if (checked) {
      const snapped = snapToTransparentSize(batchSize);
      if (snapped !== batchSize) setBatchSize(snapped);
    }
  }, [batchSize]);

  const [variations, setVariations] = useState<VariationRow[]>([
    { label: "", prompt: "", edited: false },
    { label: "", prompt: "", edited: false },
  ]);
  const [inputBrowseOpen, setInputBrowseOpen] = useState(false);
  const [sourceBrowseOpen, setSourceBrowseOpen] = useState(false);
  const [refBrowseOpen, setRefBrowseOpen] = useState(false);
  const [batchSubmitted, setBatchSubmitted] = useState<string | null>(null);

  // --- Handlers ---
  const handleFileChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    setUploadedImages(Array.from(e.target.files ?? []).slice(0, 4));
  }, []);

  const handleStop = useCallback(() => {
    stopRef.current?.();
    setGenerating(false);
  }, []);

  const handleEnhance = useCallback(async () => {
    if (!prompt.trim() && uploadedImages.length === 0) {
      toast.error("Enter a prompt (or upload an image in edit mode) first");
      return;
    }
    setEnhancing(true);
    try {
      const formData = new FormData();
      if (prompt.trim()) formData.set("prompt", prompt.trim());
      // In edit mode, ground the rewrite in the source image(s) so the rewritten
      // prompt is faithful to what's actually being edited.
      if (mode === "edit") {
        for (const file of uploadedImages.slice(0, 4)) formData.append("images", file);
      }
      const res = await fetch("/api/rewrite", { method: "POST", body: formData });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      const rewritten: string = data.rewritten ?? "";
      if (!rewritten) throw new Error("Rewrite returned empty prompt");
      setOriginalPrompt(prompt);
      setPrompt(rewritten);
      toast.success("Prompt enhanced — Revert to undo");
    } catch (err) {
      toast.error(`Enhance failed: ${err}`);
    } finally {
      setEnhancing(false);
    }
  }, [prompt, mode, uploadedImages]);

  const handleRevert = useCallback(() => {
    if (originalPrompt === null) return;
    setPrompt(originalPrompt);
    setOriginalPrompt(null);
  }, [originalPrompt]);

  const enhanceBatchPrompt = useCallback(
    async (current: string, setter: (s: string) => void) => {
      if (!current.trim()) {
        toast.error("Enter a prompt first");
        return;
      }
      setEnhancingBatch(true);
      try {
        const formData = new FormData();
        formData.set("prompt", current.trim());
        const res = await fetch("/api/rewrite", { method: "POST", body: formData });
        if (!res.ok) throw new Error(await res.text());
        const data = await res.json();
        const rewritten: string = data.rewritten ?? "";
        if (!rewritten) throw new Error("Rewrite returned empty prompt");
        setter(rewritten);
        toast.success("Prompt enhanced");
      } catch (err) {
        toast.error(`Enhance failed: ${err}`);
      } finally {
        setEnhancingBatch(false);
      }
    },
    [],
  );

  const handleSingleSubmit = useCallback(async (e: React.FormEvent) => {
    e.preventDefault();
    if (!prompt.trim()) { toast.error("Please enter a prompt"); return; }
    if (mode === "edit" && uploadedImages.length === 0) { toast.error("Please upload at least one image"); return; }

    setGenerating(true);
    setImages([]);
    const formData = new FormData();
    formData.set("prompt", prompt.trim());
    formData.set("n", String(n));
    formData.set("folder", folder);
    formData.set("quality", quality);
    formData.set("size", size);
    formData.set("output_format", outputFormat);
    if (mode === "single" || mode === "edit") {
      formData.set("background", transparent ? "transparent" : "auto");
    }
    // Resolve the selected style guideline body and ship as `criteria`.
    if (mode === "single" || mode === "edit") {
      if (styleGuidelineId !== "none") {
        const g = guidelines.find((x) => String(x.id) === styleGuidelineId);
        if (g?.body?.trim()) formData.set("criteria", g.body.trim());
      }
    }

    const url = mode === "single" ? "/api/generate" : "/api/edit";
    if (mode !== "single") {
      for (const file of uploadedImages) formData.append("images", file);
      // Pass source context so backend saves as version
      if (sourceBatchId && sourceImageId) {
        formData.set("source_batch_id", sourceBatchId);
        formData.set("source_image_id", String(sourceImageId));
      }
    }

    const cleanup = streamSSE(url, formData, {
      onPartial: (index, b64) => {
        setImages((prev) => {
          const idx = prev.findIndex((img) => img.index === index);
          if (idx >= 0) {
            const next = [...prev];
            next[idx] = { index, b64, done: false, partialCount: prev[idx].partialCount + 1 };
            return next;
          }
          return [...prev, { index, b64, done: false, partialCount: 1 }];
        });
      },
      onDone: (index, b64) => {
        setImages((prev) => {
          const idx = prev.findIndex((img) => img.index === index);
          if (idx >= 0) { const next = [...prev]; next[idx] = { ...prev[idx], b64, done: true }; return next; }
          return [...prev, { index, b64, done: true, partialCount: 3 }];
        });
      },
      onComplete: (count) => {
        toast.success(`${count} image${count !== 1 ? "s" : ""} generated and saved`);
        // Signal the gallery to keep polling for up to ~90s so it picks up
        // both phases of the backend save (Phase 1: INSERT image row,
        // Phase 2: UPDATE with eval fields after analyzer finishes).
        sessionStorage.setItem("gallery-poll-until", String(Date.now() + 90_000));
        // Show "running analysis" pill on the Generate page while the
        // backend's Phase 2 analyzer call runs. Auto-dismiss after 25s
        // (covers the 95th-percentile analyze latency).
        setAnalyzingImages(true);
        setTimeout(() => setAnalyzingImages(false), 25_000);
        // Kick an immediate invalidate so the row appears asap.
        setTimeout(() => {
          queryClient.invalidateQueries({ queryKey: ["/api/gallery"] });
          queryClient.invalidateQueries({ queryKey: listBatchesKey() });
        }, 3000);
      },
      onError: (_index, error) => toast.error(`Generation failed: ${error}`),
    }, () => setGenerating(false));
    stopRef.current = cleanup;
  }, [prompt, n, folder, quality, size, outputFormat, transparent, styleGuidelineId, guidelines, mode, uploadedImages, queryClient]);

  const updateVariationLabel = useCallback((index: number, label: string) => {
    setVariations((prev) =>
      prev.map((v, i) => {
        if (i !== index) return v;
        const newPrompt = v.edited ? v.prompt : basePrompt.replace("{variation}", label);
        return { ...v, label, prompt: newPrompt };
      })
    );
  }, [basePrompt]);

  const handleBasePromptChange = (newBase: string) => {
    setBasePrompt(newBase);
    setVariations((prev) => prev.map((v) => v.edited ? v : { ...v, prompt: newBase.replace("{variation}", v.label) }));
  };

  const handleBatchSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    // Transparent BG forces gpt-image-1.5 server-side too; we still send the user
    // selection so batch_runs records what was asked for.
    const background = batchTransparent ? "transparent" : "opaque";
    const image_model = batchTransparent ? "gpt-image-1.5" : "gpt-image-2";
    const style_guideline_id =
      batchStyleGuidelineId !== "none" ? Number(batchStyleGuidelineId) : null;

    if (batchMode === "multi_image") {
      if (!inputPath.startsWith("/Volumes/")) { toast.error("Input path must start with /Volumes/"); return; }
      if (!batchPrompt.trim()) { toast.error("Prompt template is required"); return; }
      if (!batchSizeValid) { toast.error("Fix the size before submitting"); return; }
      batchMutation.mutate(
        {
          params: {},
          data: {
            batch_name: batchName,
            batch_mode: "multi_image",
            input_volume_path: inputPath,
            reference_image_path: refPath,
            prompt_template: batchPrompt,
            size: batchSize,
            quality: batchQuality,
            image_model,
            output_format: batchOutputFormat,
            background,
            style_guideline_id,
          },
        },
        {
          onSuccess: (result) => {
            toast.success(`Batch ${result.data.batch_id} started!`);
            setBatchSubmitted(result.data.batch_id);
          },
          onError: (err) => toast.error(`Failed: ${err.message}`),
        }
      );
    } else {
      if (!sourceImagePath.startsWith("/Volumes/")) { toast.error("Source path must start with /Volumes/"); return; }
      const valid = variations.filter((v) => v.label.trim() && v.prompt.trim());
      if (valid.length < 2) { toast.error("At least 2 variations required"); return; }
      if (!batchSizeValid) { toast.error("Fix the size before submitting"); return; }
      batchMutation.mutate(
        {
          params: {},
          data: {
            batch_name: batchName,
            batch_mode: "variations",
            source_image_path: sourceImagePath,
            reference_image_path: refPath,
            prompt_template: basePrompt,
            size: batchSize,
            quality: batchQuality,
            image_model,
            output_format: batchOutputFormat,
            background,
            style_guideline_id,
            variations: valid.map((v) => ({ label: v.label.trim(), prompt: v.prompt.trim() })),
          },
        },
        {
          onSuccess: (result) => {
            toast.success(`Variations batch ${result.data.batch_id} started!`);
            setBatchSubmitted(result.data.batch_id);
          },
          onError: (err) => toast.error(`Failed: ${err.message}`),
        }
      );
    }
  };

  return (
    <div className="min-h-screen bg-background flex flex-col">
      <Navbar />
      <div className="flex-1 flex flex-col lg:flex-row gap-0">
        {/* Controls panel */}
        <aside className="w-full lg:w-[26rem] shrink-0 border-r p-4 flex flex-col overflow-y-auto max-h-[calc(100vh-4rem)]">
          {/* Three-way mode toggle */}
          <div className="flex rounded-lg border p-1 bg-muted/30 mb-3">
            <button type="button" className={`flex-1 py-1.5 px-2 rounded-md text-sm font-medium transition-colors ${mode === "single" ? "bg-background shadow-sm" : "text-muted-foreground hover:text-foreground"}`} onClick={() => { setMode("single"); setSourceBatchId(null); setSourceImageId(null); }}>
              Single
            </button>
            <button type="button" className={`flex-1 py-1.5 px-2 rounded-md text-sm font-medium transition-colors ${mode === "edit" ? "bg-background shadow-sm" : "text-muted-foreground hover:text-foreground"}`} onClick={() => setMode("edit")}>
              Edit
            </button>
            <button type="button" className={`flex-1 py-1.5 px-2 rounded-md text-sm font-medium transition-colors ${mode === "batch" ? "bg-background shadow-sm" : "text-muted-foreground hover:text-foreground"}`} onClick={() => setMode("batch")}>
              Batch
            </button>
          </div>

          {/* Single / Edit form */}
          {(mode === "single" || mode === "edit") && (
            <form onSubmit={handleSingleSubmit} className="space-y-3">
              {mode === "edit" && (
                <div className="space-y-2">
                  <Label>Source Images (up to 4)</Label>
                  <div
                    className="border-2 border-dashed rounded-lg p-2 text-center cursor-pointer hover:bg-muted/30 transition-colors flex items-center justify-center gap-2"
                    onClick={() => fileInputRef.current?.click()}
                    onDragOver={(e) => {
                      e.preventDefault();
                      e.currentTarget.classList.add("border-primary", "bg-primary/10");
                    }}
                    onDragLeave={(e) => {
                      e.currentTarget.classList.remove("border-primary", "bg-primary/10");
                    }}
                    onDrop={(e) => {
                      e.preventDefault();
                      e.currentTarget.classList.remove("border-primary", "bg-primary/10");
                      const accepted = ["image/png", "image/jpeg", "image/webp"];
                      const dropped = Array.from(e.dataTransfer.files).filter((f) => accepted.includes(f.type));
                      if (dropped.length === 0) {
                        toast.error("Drop PNG, JPEG, or WebP files");
                        return;
                      }
                      setUploadedImages((prev) => [...prev, ...dropped].slice(0, 4));
                    }}
                  >
                    <Upload className="h-4 w-4 text-muted-foreground" />
                    <p className="text-sm text-muted-foreground">Drop images here or click to upload</p>
                  </div>
                  <input ref={fileInputRef} type="file" accept="image/png,image/jpeg,image/webp" multiple className="hidden" onChange={handleFileChange} />
                  {uploadedImages.length > 0 && (
                    <div className="grid grid-cols-2 gap-2">
                      {uploadedImages.map((file, i) => (
                        <div key={i} className="relative group">
                          <img src={URL.createObjectURL(file)} alt={file.name} className="w-full aspect-square object-cover rounded-md border" />
                          <button type="button" className="absolute top-1 right-1 bg-black/60 text-white rounded-full p-0.5 opacity-0 group-hover:opacity-100 transition-opacity" onClick={() => setUploadedImages((prev) => prev.filter((_, j) => j !== i))}>
                            <X className="h-3 w-3" />
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <Label htmlFor="prompt">Prompt</Label>
                  <div className="flex items-center gap-2 text-xs">
                    {originalPrompt !== null && (
                      <button type="button" onClick={handleRevert} className="text-muted-foreground hover:text-foreground underline">
                        Revert
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={handleEnhance}
                      disabled={enhancing || generating}
                      className="inline-flex items-center gap-1 text-blue-700 dark:text-blue-400 hover:text-blue-900 disabled:opacity-50 disabled:cursor-not-allowed"
                      title="Rewrite the prompt for better image generation"
                    >
                      <Sparkles className="h-3 w-3" />
                      {enhancing ? "Enhancing…" : "Enhance"}
                    </button>
                  </div>
                </div>
                <Textarea id="prompt" value={prompt} onChange={(e) => { setPrompt(e.target.value); if (originalPrompt !== null) setOriginalPrompt(null); }} placeholder={mode === "single" ? "Describe the image..." : "Describe the changes..."} rows={3} className="resize-y" />
              </div>

              <div className="grid grid-cols-2 gap-2">
                <div className="space-y-1">
                  <Label className="text-xs">Quality</Label>
                  <Select value={quality} onValueChange={setQuality}><SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="auto">Auto</SelectItem><SelectItem value="low">Low</SelectItem><SelectItem value="medium">Medium</SelectItem><SelectItem value="high">High</SelectItem></SelectContent></Select>
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Size</Label>
                  <SizeSelectAdvanced value={size} onChange={setSize} transparent={transparent} onValidityChange={setSizeValid} />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Format</Label>
                  <Select value={outputFormat} onValueChange={setOutputFormat}><SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="png">PNG</SelectItem><SelectItem value="jpeg">JPEG</SelectItem><SelectItem value="webp">WebP</SelectItem></SelectContent></Select>
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Count</Label>
                  <Select value={String(n)} onValueChange={(v) => setN(Number(v))}><SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger><SelectContent>{[1, 2, 3, 4].map((i) => (<SelectItem key={i} value={String(i)}>{i}</SelectItem>))}</SelectContent></Select>
                </div>
              </div>

              {(mode === "single" || mode === "edit") && (
                <div className="space-y-2">
                  <label className="flex items-center gap-2 text-xs cursor-pointer select-none">
                    <input
                      type="checkbox"
                      checked={transparent}
                      onChange={(e) => handleTransparentToggle(e.target.checked)}
                      className="rounded border-input"
                    />
                    <span>Transparent background</span>
                    {transparent && (
                      <span className="text-muted-foreground">— uses gpt-image-1.5</span>
                    )}
                  </label>
                  <div className="space-y-1">
                    <Label className="text-xs">Style guideline</Label>
                    <Select value={styleGuidelineId} onValueChange={setStyleGuidelineId}>
                      <SelectTrigger className="h-8 text-xs">
                        {/* Custom trigger label — Radix's SelectValue derives text from a
                            registered SelectItemText, which only mounts after the dropdown
                            first opens. Rendering the label directly avoids the blank trigger. */}
                        <span>
                          {(() => {
                            if (styleGuidelineId === "none") return "None";
                            const sel = guidelines.find((g) => String(g.id) === styleGuidelineId);
                            return sel ? `${sel.name}${sel.is_default ? " · default" : ""}` : "None";
                          })()}
                        </span>
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
                    {guidelines.length === 0 && (
                      <p className="text-[10px] text-muted-foreground">
                        No guidelines yet. Manage in <Link to="/settings" className="underline hover:text-foreground">Settings</Link>.
                      </p>
                    )}
                  </div>
                </div>
              )}

              <div className="space-y-2">
                <Label>Save to folder</Label>
                <Select value={folder} onValueChange={setFolder}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent>{folders.map((f: any) => (<SelectItem key={f.name} value={f.name}>{f.name}</SelectItem>))}{folders.length === 0 && <SelectItem value="default">default</SelectItem>}</SelectContent></Select>
                {sourceBatchId && sourceImageId && (
                  <p className="text-[10px] text-muted-foreground">Editing from gallery — defaults to the source's folder.</p>
                )}
              </div>

              <div className="flex gap-2 pt-2">
                <Button type="submit" className="flex-1" disabled={generating || !prompt.trim() || !sizeValid}>
                  <Sparkles className="h-4 w-4 mr-2" />
                  {generating ? "Generating..." : mode === "single" ? "Generate" : "Edit"}
                </Button>
                {generating && (
                  <Button type="button" variant="outline" size="icon" onClick={handleStop}><StopCircle className="h-4 w-4" /></Button>
                )}
              </div>
            </form>
          )}

          {/* Batch form */}
          {mode === "batch" && (
            <form onSubmit={handleBatchSubmit} className="space-y-4">
              <div className="flex rounded-lg border p-1 bg-muted/30">
                <button type="button" className={`flex-1 py-1.5 px-2 rounded-md text-xs font-medium transition-colors ${batchMode === "multi_image" ? "bg-background shadow-sm" : "text-muted-foreground hover:text-foreground"}`} onClick={() => setBatchMode("multi_image")}>
                  Multiple Images
                </button>
                <button type="button" className={`flex-1 py-1.5 px-2 rounded-md text-xs font-medium transition-colors ${batchMode === "variations" ? "bg-background shadow-sm" : "text-muted-foreground hover:text-foreground"}`} onClick={() => setBatchMode("variations")}>
                  Variations
                </button>
              </div>
              <p className="text-xs text-muted-foreground">{batchMode === "multi_image" ? "N images × 1 prompt = N outputs" : "1 image × N prompts = N outputs"}</p>

              <div className="space-y-2">
                <Label>Batch Name</Label>
                <Input value={batchName} onChange={(e) => setBatchName(e.target.value)} />
              </div>

              {batchMode === "multi_image" ? (
                <div className="space-y-2">
                  <Label>Input Volume Path</Label>
                  <div className="flex gap-2">
                    <Input value={inputPath} onChange={(e) => setInputPath(e.target.value)} placeholder="/Volumes/..." className="flex-1 text-xs" />
                    <Button type="button" variant="outline" size="icon" onClick={() => setInputBrowseOpen(true)}><FolderOpen className="h-4 w-4" /></Button>
                  </div>
                  <VolumeBrowserDialog open={inputBrowseOpen} onOpenChange={setInputBrowseOpen} onSelect={setInputPath} mode="directory" />
                </div>
              ) : (
                <div className="space-y-2">
                  <Label>Source Image</Label>
                  <div className="flex gap-2">
                    <Input value={sourceImagePath} onChange={(e) => setSourceImagePath(e.target.value)} placeholder="/Volumes/..." className="flex-1 text-xs" />
                    <Button type="button" variant="outline" size="icon" onClick={() => setSourceBrowseOpen(true)}><FolderOpen className="h-4 w-4" /></Button>
                  </div>
                  <VolumeBrowserDialog open={sourceBrowseOpen} onOpenChange={setSourceBrowseOpen} onSelect={setSourceImagePath} mode="file" fileFilter={[".png", ".jpg", ".jpeg", ".webp"]} />
                </div>
              )}

              <div className="space-y-2">
                <Label>Reference Image <span className="text-muted-foreground text-xs">(optional)</span></Label>
                <div className="flex gap-2">
                  <Input value={refPath} onChange={(e) => setRefPath(e.target.value)} placeholder="/Volumes/..." className="flex-1 text-xs" />
                  <Button type="button" variant="outline" size="icon" onClick={() => setRefBrowseOpen(true)}><FolderOpen className="h-4 w-4" /></Button>
                </div>
                <VolumeBrowserDialog open={refBrowseOpen} onOpenChange={setRefBrowseOpen} onSelect={setRefPath} mode="file" fileFilter={[".png", ".jpg", ".jpeg", ".webp"]} />
              </div>

              <div className="grid grid-cols-2 gap-2">
                <div className="space-y-1">
                  <Label className="text-xs">Size</Label>
                  <SizeSelectAdvanced
                    value={batchSize}
                    onChange={setBatchSize}
                    transparent={batchTransparent}
                    onValidityChange={setBatchSizeValid}
                  />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Quality</Label>
                  <Select value={batchQuality} onValueChange={setBatchQuality}>
                    <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="auto">Auto</SelectItem>
                      <SelectItem value="low">Low</SelectItem>
                      <SelectItem value="medium">Medium</SelectItem>
                      <SelectItem value="high">High</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Format</Label>
                  <Select value={batchOutputFormat} onValueChange={setBatchOutputFormat}>
                    <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="png">PNG</SelectItem>
                      <SelectItem value="jpeg">JPEG</SelectItem>
                      <SelectItem value="webp">WebP</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Style guideline</Label>
                  <Select value={batchStyleGuidelineId} onValueChange={setBatchStyleGuidelineId}>
                    <SelectTrigger className="h-8 text-xs">
                      <span>
                        {(() => {
                          if (batchStyleGuidelineId === "none") return "None";
                          const sel = guidelines.find((g) => String(g.id) === batchStyleGuidelineId);
                          return sel ? `${sel.name}${sel.is_default ? " · default" : ""}` : "None";
                        })()}
                      </span>
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
                </div>
              </div>

              <label className="flex items-center gap-2 text-xs cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={batchTransparent}
                  onChange={(e) => handleBatchTransparentToggle(e.target.checked)}
                  className="rounded border-input"
                />
                <span>Transparent background</span>
                {batchTransparent && (
                  <span className="text-muted-foreground">— uses gpt-image-1.5</span>
                )}
              </label>

              {batchMode === "multi_image" ? (
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <Label>Prompt Template</Label>
                    <button
                      type="button"
                      onClick={() => enhanceBatchPrompt(batchPrompt, setBatchPrompt)}
                      disabled={enhancingBatch || batchMutation.isPending}
                      className="inline-flex items-center gap-1 text-xs text-blue-700 dark:text-blue-400 hover:text-blue-900 disabled:opacity-50 disabled:cursor-not-allowed"
                      title="Rewrite the prompt for better image generation"
                    >
                      <Sparkles className="h-3 w-3" />
                      {enhancingBatch ? "Enhancing…" : "Enhance"}
                    </button>
                  </div>
                  <Textarea value={batchPrompt} onChange={(e) => setBatchPrompt(e.target.value)} rows={7} className="font-mono text-xs" />
                  <p className="text-xs text-muted-foreground">Use <code className="bg-muted px-1 rounded">{"{image_name}"}</code> as placeholder.</p>
                </div>
              ) : (
                <>
                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <Label>Base Prompt</Label>
                      <button
                        type="button"
                        onClick={() => enhanceBatchPrompt(basePrompt, (v) => handleBasePromptChange(v))}
                        disabled={enhancingBatch || batchMutation.isPending}
                        className="inline-flex items-center gap-1 text-xs text-blue-700 dark:text-blue-400 hover:text-blue-900 disabled:opacity-50 disabled:cursor-not-allowed"
                        title="Rewrite the prompt for better image generation"
                      >
                        <Sparkles className="h-3 w-3" />
                        {enhancingBatch ? "Enhancing…" : "Enhance"}
                      </button>
                    </div>
                    <Textarea value={basePrompt} onChange={(e) => handleBasePromptChange(e.target.value)} rows={3} className="font-mono text-xs" />
                    <p className="text-xs text-muted-foreground">Use <code className="bg-muted px-1 rounded">{"{variation}"}</code> for the variation label, and optionally <code className="bg-muted px-1 rounded">{"{image_name}"}</code> for the source image's filename.</p>
                  </div>
                  <div className="space-y-2">
                    <Label>Variations</Label>
                    {variations.map((v, i) => (
                      <div key={i} className="flex gap-1 items-center">
                        <span className="text-xs text-muted-foreground w-4 shrink-0">{i + 1}.</span>
                        <Input value={v.label} onChange={(e) => updateVariationLabel(i, e.target.value)} placeholder="Label" className="flex-1 text-sm" />
                        {variations.length > 2 && (
                          <Button type="button" variant="ghost" size="icon" className="shrink-0 h-7 w-7" onClick={() => setVariations((prev) => prev.filter((_, j) => j !== i))}>
                            <X className="h-3 w-3" />
                          </Button>
                        )}
                      </div>
                    ))}
                    <Button type="button" variant="outline" size="sm" onClick={() => setVariations((prev) => [...prev, { label: "", prompt: "", edited: false }])}>
                      <Plus className="h-3 w-3 mr-1" />Add
                    </Button>
                  </div>
                </>
              )}

              <Button type="submit" className="w-full" disabled={batchMutation.isPending || !batchSizeValid}>
                <Sparkles className="h-4 w-4 mr-2" />
                {batchMutation.isPending ? "Starting..." : "Generate Batch"}
              </Button>
            </form>
          )}

        </aside>

        {/* Preview panel */}
        <main className="flex-1 p-6">
          {mode === "batch" ? (
            batchSubmitted ? (
              <BatchDetailContent
                batchId={batchSubmitted}
                onDeleted={() => setBatchSubmitted(null)}
              />
            ) : (
              <div className="flex flex-col items-center justify-center h-full min-h-64 text-center">
                <ImagePlus className="h-16 w-16 text-muted-foreground mb-4" />
                <h3 className="text-lg font-medium text-muted-foreground">Batch Generation</h3>
                <p className="text-sm text-muted-foreground mt-1">Configure your batch and click Generate Batch</p>
              </div>
            )
          ) : generating && images.length === 0 ? (
            /* Skeleton placeholders — shown immediately after clicking Generate */
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
              {Array.from({ length: n }).map((_, i) => (
                <div key={i} className="aspect-square rounded-lg bg-muted/50 border relative overflow-hidden animate-shimmer">
                  <div className="absolute inset-0 flex flex-col items-center justify-center gap-3">
                    <Sparkles className="h-8 w-8 text-muted-foreground/50 animate-pulse" />
                    <p className="text-sm text-muted-foreground/50">Generating...</p>
                  </div>
                </div>
              ))}
            </div>
          ) : images.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full min-h-64 text-center">
              <ImagePlus className="h-16 w-16 text-muted-foreground mb-4" />
              <h3 className="text-lg font-medium text-muted-foreground">No images yet</h3>
              <p className="text-sm text-muted-foreground mt-1">Enter a prompt and click Generate</p>
            </div>
          ) : (
            <div className="space-y-3">
              {analyzingImages && (
                <div className="inline-flex items-center gap-2 rounded-full border border-blue-500/30 bg-blue-500/5 px-3 py-1.5 text-xs text-blue-700 dark:text-blue-400">
                  <Sparkles className="h-3.5 w-3.5 animate-pulse" />
                  <span>Running image analysis — evaluation will appear in the gallery shortly</span>
                </div>
              )}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
              {images.map((img) => {
                const blurClass = img.done
                  ? "animate-reveal"
                  : img.partialCount <= 1
                    ? "blur-lg opacity-40 scale-[1.05]"
                    : img.partialCount === 2
                      ? "blur-md opacity-60 scale-[1.03]"
                      : "blur-sm opacity-80 scale-[1.01]";
                return (
                  <div key={img.index} className="relative rounded-lg overflow-hidden border bg-muted">
                    <img
                      src={`data:image/png;base64,${img.b64}`}
                      alt={`Generated ${img.index + 1}`}
                      className={`w-full transition-all duration-[2s] ease-out ${blurClass}`}
                    />
                    {!img.done && (
                      <div className="absolute bottom-0 left-0 right-0 h-1 bg-muted/50">
                        <div
                          className="h-full bg-primary/60 transition-all duration-1000 ease-out"
                          style={{ width: `${Math.min((img.partialCount / 3) * 85, 85)}%` }}
                        />
                      </div>
                    )}
                    {img.done && (
                      <div className="absolute top-2 right-2 animate-badge-in">
                        <Badge className="bg-green-600 text-white text-xs">Saved</Badge>
                      </div>
                    )}
                  </div>
                );
              })}
              </div>
            </div>
          )}
        </main>
      </div>

    </div>
  );
}
