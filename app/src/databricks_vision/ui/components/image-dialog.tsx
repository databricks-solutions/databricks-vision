/**
 * ImageDialog — unified image detail dialog.
 * Shows image, metadata, and actions: Delete, Edit, Download.
 */
import { useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import { useQueryClient } from "@tanstack/react-query";
import { getBatchDetailKey, listBatchesKey } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
} from "@/components/ui/dialog";
import { Copy, Download, Edit3, Search, Sparkles, Trash2 } from "lucide-react";
import { toast } from "sonner";

export type ImageMetrics = {
  quality: number;
  prompt_adherence: number;
  purpose_fit: number;
  text_legibility: number;
  safe_content: number;
};

export type ImageDialogImage = {
  id: number;
  batch_id: string;
  image_name: string | null;
  prompt: string | null;
  status: string | null;
  volume_path: string | null;
  variation_label: string | null;
  folder?: string | null;
  description: string | null;
  tags: string[];
  thumbnail_path: string | null;
  version_count?: number;
  reference_image_path?: string | null;
  input_image_path?: string | null;
  // Eval fields populated by ImageAnalyzer
  evaluation?: string | null;
  metrics?: ImageMetrics | null;
  missing_elements?: string[];
  safety_flags?: string[];
  brand_conflicts?: string[];
  improved_prompt?: string | null;
  criteria_evaluation?: string | null;
};

const METRIC_LABELS: { key: keyof ImageMetrics; label: string }[] = [
  { key: "quality", label: "Quality" },
  { key: "prompt_adherence", label: "Prompt" },
  { key: "purpose_fit", label: "Purpose" },
  { key: "text_legibility", label: "Text" },
  { key: "safe_content", label: "Safe" },
];

function metricColor(score: number): string {
  if (score >= 4) return "bg-green-500/15 text-green-700 dark:text-green-400 border-green-500/30";
  if (score >= 3) return "bg-yellow-500/15 text-yellow-700 dark:text-yellow-400 border-yellow-500/30";
  return "bg-red-500/15 text-red-700 dark:text-red-400 border-red-500/30";
}

function imageSrc(img: ImageDialogImage): string {
  // Single-gen images (have thumbnail_path) are served via gallery endpoint
  if (img.thumbnail_path) {
    return `/api/gallery/${img.batch_id}/${img.id}/file`;
  }
  // Batch images served via batch-images endpoint
  if (img.volume_path) {
    const lastSlash = img.volume_path.lastIndexOf("/");
    const filename = lastSlash >= 0 ? img.volume_path.substring(lastSlash + 1) : img.volume_path;
    return `/api/batch-images/${img.batch_id}/${filename}`;
  }
  return `/api/batch-images/${img.batch_id}/${img.image_name}_generated.jpeg`;
}

interface ImageDialogProps {
  image: ImageDialogImage | null;
  open: boolean;
  onClose: () => void;
  onDeleted?: () => void;
  onFindSimilar?: (image: ImageDialogImage) => void;
}

export function ImageDialog({ image, open, onClose, onDeleted, onFindSimilar }: ImageDialogProps) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [showDelete, setShowDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [lightbox, setLightbox] = useState(false);

  function invalidateAll() {
    queryClient.invalidateQueries({ queryKey: ["/api/gallery"] });
    queryClient.invalidateQueries({ queryKey: listBatchesKey() });
    if (image?.batch_id) {
      queryClient.invalidateQueries({ queryKey: getBatchDetailKey({ batch_id: image.batch_id }) });
    }
  }

  async function handleDelete() {
    if (!image) return;
    setDeleting(true);
    try {
      const res = await fetch(`/api/gallery/${image.batch_id}/${image.id}`, { method: "DELETE" });
      if (!res.ok) throw new Error(await res.text());
      toast.success("Image deleted");
      setShowDelete(false);
      onClose();
      onDeleted?.();
      invalidateAll();
    } catch (e) {
      toast.error(`Failed to delete: ${e}`);
    } finally {
      setDeleting(false);
    }
  }

  async function handleAnalyze() {
    if (!image) return;
    setAnalyzing(true);
    try {
      const res = await fetch(
        `/api/gallery/${image.batch_id}/${image.id}/analyze`,
        { method: "POST" },
      );
      if (!res.ok) throw new Error(await res.text());
      toast.success("Analysis complete");
      invalidateAll();
      onClose();
    } catch (e) {
      toast.error(`Analyze failed: ${e}`);
    } finally {
      setAnalyzing(false);
    }
  }

  async function handleEdit() {
    if (!image) return;
    try {
      // Fetch the generated image
      const src = imageSrc(image);
      const res = await fetch(src);
      if (!res.ok) throw new Error("Failed to fetch image");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const filename = image.image_name ?? "image";
      const ext = image.volume_path?.match(/\.\w+$/)?.[0] ?? ".png";
      sessionStorage.setItem("edit-image-blob-url", url);
      sessionStorage.setItem("edit-image-filename", `${filename}${ext}`);
      sessionStorage.setItem("edit-image-prompt", image.prompt ?? "");
      sessionStorage.setItem("edit-source-batch-id", image.batch_id);
      sessionStorage.setItem("edit-source-image-id", String(image.id));
      // Pre-select the source's folder on the Generate form so edits land
      // alongside the original by default. User can still change it.
      if (image.folder) sessionStorage.setItem("edit-source-folder", image.folder);
      else sessionStorage.removeItem("edit-source-folder");

      // Also fetch reference image if available (from batch)
      const refPath = image.reference_image_path;
      if (refPath) {
        try {
          const refRes = await fetch(`/api/batch-images/source?path=${encodeURIComponent(refPath)}`);
          if (refRes.ok) {
            const refBlob = await refRes.blob();
            sessionStorage.setItem("edit-ref-blob-url", URL.createObjectURL(refBlob));
            sessionStorage.setItem("edit-ref-filename", refPath.split("/").pop() ?? "reference.png");
          }
        } catch { /* reference is optional */ }
      }

      // Also fetch original input image if available
      const inputPath = image.input_image_path;
      if (inputPath) {
        try {
          const inputRes = await fetch(`/api/batch-images/source?path=${encodeURIComponent(inputPath)}`);
          if (inputRes.ok) {
            const inputBlob = await inputRes.blob();
            sessionStorage.setItem("edit-input-blob-url", URL.createObjectURL(inputBlob));
            sessionStorage.setItem("edit-input-filename", inputPath.split("/").pop() ?? "input.png");
          }
        } catch { /* input is optional */ }
      }

      navigate({ to: "/generate" });
      onClose();
    } catch (e) {
      toast.error(`Failed to load image for editing: ${e}`);
    }
  }

  if (!image) return null;

  const displayName = image.variation_label || image.image_name?.replace(/_/g, " ") || "Image";
  const src = imageSrc(image);

  return (
    <>
      {/* Main image dialog */}
      <Dialog open={open && !showDelete} onOpenChange={(o) => !o && onClose()}>
        <DialogContent className="max-w-4xl max-h-[90vh] overflow-y-auto">
          <DialogTitle className="flex items-center gap-2 pr-8">
            <span className="truncate">{displayName}</span>
          </DialogTitle>
          <div className="grid md:grid-cols-2 gap-4">
            <img
              src={src}
              alt={displayName}
              className="w-full rounded-lg object-contain max-h-[60vh] cursor-zoom-in"
              title="Click to view full resolution"
              onClick={() => setLightbox(true)}
            />
            <div className="space-y-3 text-sm">
              {image.prompt && (
                <div>
                  <p className="font-medium text-muted-foreground mb-1">Prompt</p>
                  <p className="text-foreground text-xs">{image.prompt}</p>
                </div>
              )}
              {image.description && (
                <div>
                  <p className="font-medium text-muted-foreground mb-1">Description</p>
                  <p className="text-foreground text-xs">{image.description}</p>
                </div>
              )}
              {(image.tags ?? []).length > 0 && (
                <div>
                  <p className="font-medium text-muted-foreground mb-1">Tags</p>
                  <div className="flex flex-wrap gap-1">
                    {image.tags.map((tag) => (
                      <Badge key={tag} variant="secondary" className="text-xs">{tag}</Badge>
                    ))}
                  </div>
                </div>
              )}
              {image.metrics && (
                <div>
                  <p className="font-medium text-muted-foreground mb-1">Evaluation</p>
                  <div className="grid grid-cols-5 gap-1 mb-2">
                    {METRIC_LABELS.map(({ key, label }) => {
                      const score = image.metrics?.[key] ?? 0;
                      return (
                        <div key={key} className={`flex flex-col items-center gap-0.5 rounded-md border px-1 py-1.5 ${metricColor(score)}`} title={`${label}: ${score}/5`}>
                          <span className="text-[10px] font-medium uppercase tracking-wide leading-none">{label}</span>
                          <span className="text-sm font-semibold leading-none">{score}</span>
                        </div>
                      );
                    })}
                  </div>
                  {image.evaluation && (
                    <p className="text-foreground text-xs leading-snug">{image.evaluation}</p>
                  )}
                </div>
              )}
              {image.metrics && (() => {
                // Once the analyzer has run (image.metrics populated), always render
                // Issues found and Suggested improved prompt so the layout stays
                // consistent — empty states render a muted "none" message inside.
                const missing = image.missing_elements ?? [];
                const safety = image.safety_flags ?? [];
                const brand = image.brand_conflicts ?? [];
                const totalIssues = missing.length + safety.length + brand.length;
                return (
                  <>
                    <details className="text-xs">
                      <summary className="font-medium text-muted-foreground cursor-pointer hover:text-foreground">
                        Issues found ({totalIssues})
                      </summary>
                      <div className="mt-1.5 space-y-1.5 pl-2 border-l-2 border-border">
                        {totalIssues === 0 && (
                          <p className="text-muted-foreground italic">No issues detected.</p>
                        )}
                        {missing.length > 0 && (
                          <div>
                            <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Missing or wrong</p>
                            <ul className="list-disc list-inside text-foreground">
                              {missing.map((s, i) => <li key={i}>{s}</li>)}
                            </ul>
                          </div>
                        )}
                        {safety.length > 0 && (
                          <div>
                            <p className="text-[10px] uppercase tracking-wide text-red-600 dark:text-red-400">Safety</p>
                            <ul className="list-disc list-inside text-foreground">
                              {safety.map((s, i) => <li key={i}>{s}</li>)}
                            </ul>
                          </div>
                        )}
                        {brand.length > 0 && (
                          <div>
                            <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Brand conflicts</p>
                            <ul className="list-disc list-inside text-foreground">
                              {brand.map((s, i) => <li key={i}>{s}</li>)}
                            </ul>
                          </div>
                        )}
                      </div>
                    </details>
                    <details className="text-xs">
                      <summary className="font-medium text-muted-foreground cursor-pointer hover:text-foreground">
                        Suggested improved prompt
                      </summary>
                      <div className="mt-1.5 rounded-md border border-blue-500/30 bg-blue-500/5 p-2 text-foreground space-y-1.5">
                        {image.improved_prompt ? (
                          <>
                            <p className="leading-snug">{image.improved_prompt}</p>
                            <button
                              className="inline-flex items-center gap-1 text-[11px] text-blue-700 dark:text-blue-400 hover:underline"
                              onClick={() => { navigator.clipboard.writeText(image.improved_prompt!); toast.success("Improved prompt copied"); }}
                            >
                              <Copy className="h-3 w-3" /> Copy
                            </button>
                          </>
                        ) : (
                          <p className="text-muted-foreground italic">No improvements suggested.</p>
                        )}
                      </div>
                    </details>
                  </>
                );
              })()}
              {image.criteria_evaluation && (
                <div>
                  <p className="font-medium text-muted-foreground mb-1">Criteria evaluation</p>
                  <p className="text-foreground text-xs whitespace-pre-line">{image.criteria_evaluation}</p>
                </div>
              )}
              {image.volume_path && (
                <div>
                  <p className="font-medium text-muted-foreground mb-1">Volume Path</p>
                  <div className="flex items-center gap-1">
                    <p className="text-xs font-mono text-muted-foreground truncate">{image.volume_path}</p>
                    <button className="shrink-0 text-muted-foreground hover:text-foreground" onClick={() => { navigator.clipboard.writeText(image.volume_path!); toast.success("Copied!"); }}>
                      <Copy className="h-3 w-3" />
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
          <DialogFooter className="flex flex-wrap gap-2 sm:justify-between">
            <Button variant="destructive" size="sm" className="text-white" onClick={() => setShowDelete(true)}>
              <Trash2 className="h-4 w-4 mr-1" />Delete
            </Button>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={handleAnalyze}
                disabled={analyzing}
                title={image.metrics ? "Re-run analyzer + embedder" : "Run analyzer + embedder for this image"}
              >
                <Sparkles className="h-4 w-4 mr-1" />
                {analyzing ? "Analyzing…" : image.metrics ? "Re-analyze" : "Analyze"}
              </Button>
              {onFindSimilar && (
                <Button variant="outline" size="sm" onClick={() => onFindSimilar(image)}>
                  <Search className="h-4 w-4 mr-1" />Find similar
                </Button>
              )}
              <Button variant="outline" size="sm" onClick={handleEdit}>
                <Edit3 className="h-4 w-4 mr-1" />Edit
              </Button>
              <Button variant="outline" size="sm" asChild>
                <a href={imageSrc(image)} download={image.image_name ?? "image"}>
                  <Download className="h-4 w-4 mr-1" />Download
                </a>
              </Button>
            </div>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Full-resolution lightbox — nested Dialog so it plays nicely with the parent's focus trap */}
      <Dialog open={lightbox} onOpenChange={setLightbox}>
        <DialogContent
          hideClose
          className="!max-w-[98vw] !w-auto max-h-[98vh] !p-0 border-0 bg-transparent shadow-none sm:rounded-none data-[state=open]:zoom-in-100 data-[state=closed]:zoom-out-100 [&>button[type='button']]:hidden"
        >
          <DialogTitle className="sr-only">{displayName} — full resolution</DialogTitle>
          <img
            src={src}
            alt={displayName}
            className="max-w-full max-h-[98vh] object-contain cursor-zoom-out"
            onClick={() => setLightbox(false)}
          />
        </DialogContent>
      </Dialog>

      {/* Delete confirmation */}
      <Dialog open={showDelete} onOpenChange={(o) => !o && setShowDelete(false)}>
        <DialogContent>
          <DialogTitle>Delete image?</DialogTitle>
          <DialogDescription>This will permanently delete the image and its files from the volume.</DialogDescription>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowDelete(false)} disabled={deleting}>Cancel</Button>
            <Button variant="destructive" className="text-white" onClick={handleDelete} disabled={deleting}>
              {deleting ? "Deleting..." : "Delete"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
