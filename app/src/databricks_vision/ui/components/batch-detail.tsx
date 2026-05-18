/**
 * BatchDetailContent — reusable batch detail view.
 * Extracted from batch.$batchId.tsx for use inline in the gallery.
 */
import React, { Suspense, useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import { ErrorBoundary } from "react-error-boundary";
import {
  useGetBatchDetail,
  useGetBatchStatus,
  useGetAppConfig,
  getBatchDetailKey,
  listBatchesKey,
  listGalleryImagesKey,
  type BatchDetailOut,
  type BatchRunOut,
  type GeneratedImageOut,
  type AppConfigOut,
} from "@/lib/api";
import { useQueryClient } from "@tanstack/react-query";
import { ImageDialog, type ImageDialogImage } from "@/components/image-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { Copy, ExternalLink, RefreshCw, Sparkles, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { selector } from "@/lib/selector";

function filenameFromPath(volumePath: string | null | undefined): string | null {
  if (!volumePath) return null;
  const lastSlash = volumePath.lastIndexOf("/");
  return lastSlash >= 0 ? volumePath.substring(lastSlash + 1) : volumePath;
}

function imageSrc(batchId: string, img: GeneratedImageOut): string {
  const filename = filenameFromPath(img.volume_path);
  if (filename) return `/api/batch-images/${batchId}/${filename}`;
  return `/api/batch-images/${batchId}/${img.image_name}_generated.jpeg`;
}

function volumeFolderUrl(workspaceUrl: string, orgId: string, folderPath: string): string {
  const withoutPrefix = folderPath.replace(/^\/Volumes\//, "").replace(/\/$/, "");
  const parts = withoutPrefix.split("/");
  const [catalog, schema, volume, ...rest] = parts;
  if (!catalog || !schema || !volume) return "";
  const base = `${workspaceUrl}/explore/data/volumes/${catalog}/${schema}/${volume}`;
  const subpath = rest.filter(Boolean).join("/");
  const volumePathParam = `/Volumes/${catalog}/${schema}/${volume}${subpath ? `/${subpath}` : ""}/`;
  const params = new URLSearchParams();
  if (subpath) params.set("path", `/${subpath}`);
  if (orgId) params.set("o", orgId);
  params.set("volumePath", volumePathParam);
  const qs = params.toString();
  return qs ? `${base}?${qs}` : base;
}

function volumeFileUrl(workspaceUrl: string, orgId: string, filePath: string): string {
  const lastSlash = filePath.lastIndexOf("/");
  const folderPath = filePath.substring(0, lastSlash);
  const filename = filePath.substring(lastSlash + 1);
  const withoutPrefix = folderPath.replace(/^\/Volumes\//, "").replace(/\/$/, "");
  const parts = withoutPrefix.split("/");
  const [catalog, schema, volume, ...rest] = parts;
  if (!catalog || !schema || !volume || !filename) return "";
  const base = `${workspaceUrl}/explore/data/volumes/${catalog}/${schema}/${volume}`;
  const subpath = rest.filter(Boolean).join("/");
  const volumePathParam = `/Volumes/${catalog}/${schema}/${volume}${subpath ? `/${subpath}` : ""}/`;
  const params = new URLSearchParams();
  if (subpath) params.set("path", `/${subpath}`);
  if (orgId) params.set("o", orgId);
  params.set("volumePath", volumePathParam);
  params.set("filePreviewPath", filename);
  return `${base}?${params.toString()}`;
}

function VolumePath({ path, workspaceUrl, orgId, isFile }: { path: string; workspaceUrl: string; orgId: string; isFile?: boolean }) {
  const explorerUrl = isFile ? volumeFileUrl(workspaceUrl, orgId, path) : volumeFolderUrl(workspaceUrl, orgId, path);
  return (
    <span className="inline-flex items-center gap-1 font-mono text-sm">
      <span className="truncate max-w-[500px]">{path}</span>
      <button className="text-muted-foreground hover:text-foreground shrink-0" title="Copy path" onClick={() => { navigator.clipboard.writeText(path); toast.success("Copied!"); }}>
        <Copy className="h-3 w-3" />
      </button>
      {explorerUrl && (
        <a href={explorerUrl} target="_blank" rel="noopener noreferrer" className="text-muted-foreground hover:text-foreground shrink-0" title="Open in Catalog Explorer">
          <ExternalLink className="h-3 w-3" />
        </a>
      )}
    </span>
  );
}

function StatusBadge({ status }: { status: string }) {
  const variant = { pending: "secondary" as const, running: "default" as const, completed: "default" as const, failed: "destructive" as const }[status] ?? ("secondary" as const);
  return (
    <Badge variant={variant} className={status === "completed" ? "bg-green-600 text-white" : status === "failed" ? "text-white" : status === "running" ? "animate-pulse" : ""}>
      {status}
    </Badge>
  );
}

export function BatchDetailContent({ batchId, onDeleted }: { batchId: string; onDeleted?: () => void }) {
  return (
    <ErrorBoundary fallback={<div className="text-destructive">Failed to load batch</div>}>
      <Suspense fallback={<BatchDetailSkeleton />}>
        <BatchDetail batchId={batchId} onDeleted={onDeleted} />
      </Suspense>
    </ErrorBoundary>
  );
}

function BatchDetail({ batchId, onDeleted }: { batchId: string; onDeleted?: () => void }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [selectedImage, setSelectedImage] = useState<ImageDialogImage | null>(null);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [analyzeProgress, setAnalyzeProgress] = useState<{ analyzed: number; total: number } | null>(null);

  const { data: appConfig } = useGetAppConfig({ query: { ...selector<AppConfigOut>().query } });
  const workspaceUrl = appConfig?.workspace_url ?? "";
  const orgId = appConfig?.org_id ?? "";

  const { data: detail, refetch: refetchDetail, isFetching } = useGetBatchDetail({
    params: { batch_id: batchId },
    query: { ...selector<BatchDetailOut>().query, keepPreviousData: false },
  });

  const isRunning = detail?.batch.status === "running";

  const { data: statusData } = useGetBatchStatus({
    params: { batch_id: batchId },
    query: { ...selector<BatchRunOut>().query, refetchInterval: isRunning ? 10000 : false },
  });

  const currentStatus = statusData?.status ?? detail?.batch.status;
  const prevStatusRef = React.useRef(currentStatus);
  React.useEffect(() => {
    if (prevStatusRef.current === "running" && currentStatus && currentStatus !== "running") {
      refetchDetail();
    }
    prevStatusRef.current = currentStatus;
  }, [currentStatus, refetchDetail]);

  const batch = statusData ?? detail?.batch;
  const images = detail?.images ?? [];

  async function handleDelete() {
    setDeleting(true);
    try {
      const res = await fetch(`/api/batches/${batchId}`, { method: "DELETE" });
      if (!res.ok) throw new Error(await res.text());
      toast.success("Batch deleted");
      queryClient.invalidateQueries({ queryKey: listBatchesKey() });
      queryClient.invalidateQueries({ queryKey: listGalleryImagesKey() });
      onDeleted?.();
    } catch (e) {
      toast.error(`Failed to delete batch: ${e}`);
      setDeleting(false);
    }
  }

  if (!batch || isFetching) return <BatchDetailSkeleton />;

  return (
    <>
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-bold">{batch.batch_name || <span className="font-mono">{batch.batch_id}</span>}</h1>
          {batch.batch_name && <span className="text-sm text-muted-foreground font-mono">{batch.batch_id}</span>}
          <StatusBadge status={batch.status} />
          <Badge variant="outline" className="text-xs">{batch.batch_mode === "variations" ? "Variations" : "Multiple Images"}</Badge>
          {batch.status === "running" && <RefreshCw className="h-4 w-4 animate-spin text-muted-foreground" />}
        </div>
        <Button variant="ghost" size="icon" className="text-destructive hover:text-destructive" onClick={() => setShowDeleteConfirm(true)}>
          <Trash2 className="h-4 w-4" />
        </Button>
      </div>

      <div className="mb-6 space-y-2">
        <div className="text-sm text-muted-foreground space-y-1">
          {batch.batch_mode === "variations" && batch.source_image_path ? (
            <p><span className="font-medium">Source:</span> <VolumePath path={batch.source_image_path} workspaceUrl={workspaceUrl} orgId={orgId} isFile /></p>
          ) : (
            batch.input_volume_path && <p><span className="font-medium">Input:</span> <VolumePath path={batch.input_volume_path} workspaceUrl={workspaceUrl} orgId={orgId} /></p>
          )}
          {batch.reference_image_path && (
            <p><span className="font-medium">Reference:</span> <VolumePath path={batch.reference_image_path} workspaceUrl={workspaceUrl} orgId={orgId} isFile /></p>
          )}
          <p><span className="font-medium">Created by:</span> {batch.created_by ?? "-"} on {batch.created_at ? new Date(batch.created_at).toLocaleString() : "-"}{batch.size ? <> · <span className="font-medium">Size:</span> {batch.size}</> : null}</p>
          {batch.output_volume_path && (
            <p><span className="font-medium">Output:</span> <VolumePath path={batch.output_volume_path} workspaceUrl={workspaceUrl} orgId={orgId} /></p>
          )}
          {batch.total_images != null && (
            <p><span className="font-medium">Results:</span> {batch.successful_images ?? 0}/{batch.total_images} successful</p>
          )}
        </div>
        {batch.prompt_template && (
          <details className="mt-2">
            <summary className="text-sm font-medium cursor-pointer">Prompt Template</summary>
            <pre className="mt-1 text-xs bg-muted p-3 rounded-lg whitespace-pre-wrap max-h-40 overflow-auto">{batch.prompt_template}</pre>
          </details>
        )}
      </div>

      {(batch.source_image_path || batch.reference_image_path) && (
        <div className="mb-6 inline-flex items-start gap-4 p-4 border rounded-lg bg-muted/20">
          {batch.batch_mode === "variations" && batch.source_image_path && (
            <div className="text-center">
              <img src={`/api/batch-images/source?path=${encodeURIComponent(batch.source_image_path)}`} alt="Source" className="w-24 h-24 object-cover rounded-lg border" />
              <p className="text-xs font-medium mt-1">Source</p>
            </div>
          )}
          {batch.reference_image_path && (
            <div className="text-center">
              <img src={`/api/batch-images/source?path=${encodeURIComponent(batch.reference_image_path)}`} alt="Reference" className="w-24 h-24 object-cover rounded-lg border" />
              <p className="text-xs font-medium mt-1">Reference</p>
            </div>
          )}
        </div>
      )}

      {images.length === 0 && batch.status === "running" && (
        <div className="text-center py-16 border rounded-lg">
          <RefreshCw className="h-8 w-8 mx-auto animate-spin text-muted-foreground mb-4" />
          <p className="text-muted-foreground">Generation in progress... This page will update automatically.</p>
        </div>
      )}

      {/* Analyze button — shown when batch has images without descriptions */}
      {images.length > 0 && images.some((img) => img.status === "success" && !img.description) && (
        <div className="mb-4">
          <Button
            variant="outline"
            size="sm"
            disabled={analyzing}
            onClick={async () => {
              setAnalyzing(true);
              setAnalyzeProgress(null);
              try {
                const formData = new FormData();
                formData.set("batch_id", batchId);
                const res = await fetch("/api/gallery/analyze", { method: "POST", body: formData });
                if (!res.ok || !res.body) { toast.error("Analysis failed"); return; }
                const reader = res.body.getReader();
                const decoder = new TextDecoder();
                let buffer = "";
                let eventType = "";
                while (true) {
                  const { done, value } = await reader.read();
                  if (done) break;
                  buffer += decoder.decode(value, { stream: true });
                  const lines = buffer.split("\n");
                  buffer = lines.pop() ?? "";
                  for (const line of lines) {
                    if (line.startsWith("event: ")) { eventType = line.slice(7).trim(); }
                    else if (line.startsWith("data: ")) {
                      try {
                        const d = JSON.parse(line.slice(6).trim());
                        if (eventType === "progress") setAnalyzeProgress({ analyzed: d.analyzed, total: d.total });
                        if (eventType === "complete") { toast.success(`Analyzed ${d.analyzed} images`); refetchDetail(); }
                      } catch {}
                      eventType = "";
                    }
                  }
                }
              } catch (e) { toast.error(`Error: ${e}`); }
              finally { setAnalyzing(false); setAnalyzeProgress(null); }
            }}
          >
            <Sparkles className="h-4 w-4 mr-2" />
            {analyzing
              ? analyzeProgress ? `Analyzing ${analyzeProgress.analyzed}/${analyzeProgress.total}...` : "Starting analysis..."
              : "Analyze Images"}
          </Button>
          <p className="text-xs text-muted-foreground mt-1">Add AI descriptions, tags, thumbnails, and evaluations to batch images</p>
        </div>
      )}

      {images.length > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
          {images.map((img) => (
            <Card key={img.id} className="group overflow-hidden cursor-pointer hover:ring-2 hover:ring-primary transition-all" onClick={() => img.status === "success" ? setSelectedImage({ ...img, id: img.id!, batch_id: img.batch_id, tags: img.tags ?? [], description: img.description ?? null, thumbnail_path: img.thumbnail_path ?? null, reference_image_path: batch.reference_image_path, input_image_path: img.input_image_path }) : null}>
              <CardContent className="p-0">
                <div className="relative">
                  {img.status === "success" && img.volume_path ? (
                    <img src={imageSrc(batchId, img)} alt={img.image_name ?? ""} className="w-full aspect-square object-cover" loading="lazy" />
                  ) : (
                    <div className="w-full aspect-square bg-muted flex items-center justify-center">
                      <span className="text-xs text-muted-foreground">{img.status ?? "pending"}</span>
                    </div>
                  )}
                  {img.status === "success" && (img.description || (img.tags ?? []).length > 0) && (
                    <>
                      <div className="absolute inset-0 bg-black/0 group-hover:bg-black/40 transition-colors" />
                      <div className="absolute bottom-0 left-0 right-0 p-2 opacity-0 group-hover:opacity-100 transition-opacity">
                        {img.description && <p className="text-white text-xs font-medium truncate">{img.description}</p>}
                        {(img.tags ?? []).length > 0 && (
                          <div className="flex gap-1 mt-1 flex-wrap">
                            {(img.tags ?? []).slice(0, 3).map((tag: string) => (
                              <span key={tag} className="text-[10px] bg-white/20 text-white px-1 py-0.5 rounded">{tag}</span>
                            ))}
                          </div>
                        )}
                      </div>
                    </>
                  )}
                </div>
                <div className="p-2">
                  <div className="flex items-center gap-1">
                    <p className="text-sm font-medium truncate flex-1">{img.variation_label || img.image_name?.replace(/_/g, " ") || "Unknown"}</p>
                    {(img.version_count ?? 0) > 0 && <Badge variant="outline" className="text-[10px] px-1 py-0 shrink-0">v{img.version_count ?? 0}</Badge>}
                  </div>
                  {img.status !== "success" && <p className="text-xs text-destructive truncate">{img.error_message ?? img.status}</p>}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Delete confirmation */}
      <Dialog open={showDeleteConfirm} onOpenChange={setShowDeleteConfirm}>
        <DialogContent>
          <DialogTitle>Delete batch {batchId}?</DialogTitle>
          <DialogDescription>This will permanently delete the batch record and all generated image records. Files in the volume will not be removed.</DialogDescription>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowDeleteConfirm(false)} disabled={deleting}>Cancel</Button>
            <Button variant="destructive" className="text-white" onClick={handleDelete} disabled={deleting}>{deleting ? "Deleting..." : "Delete"}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Unified image dialog */}
      <ImageDialog
        image={selectedImage}
        open={!!selectedImage}
        onClose={() => setSelectedImage(null)}
        onDeleted={() => queryClient.invalidateQueries({ queryKey: getBatchDetailKey({ batch_id: batchId }) })}
        onFindSimilar={(img) => {
          // The gallery route owns the search-results view; signal it via sessionStorage
          // and navigate there.
          sessionStorage.setItem("gallery-similar-to", JSON.stringify({
            batch_id: img.batch_id,
            id: img.id,
            label: img.image_name ?? `${img.batch_id}/${img.id}`,
          }));
          navigate({ to: "/" });
        }}
      />
    </>
  );
}

function BatchDetailSkeleton() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-8 w-64" />
      <Skeleton className="h-4 w-96" />
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4 mt-6">
        {[1, 2, 3, 4, 5, 6].map((i) => <Skeleton key={i} className="aspect-square rounded-lg" />)}
      </div>
    </div>
  );
}
