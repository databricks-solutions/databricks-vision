import { createFileRoute } from "@tanstack/react-router";
import { useState, useEffect, useRef } from "react";
import Navbar from "@/components/apx/navbar";
import { BatchDetailContent } from "@/components/batch-detail";
import { ImageDialog, type ImageDialogImage } from "@/components/image-dialog";
import type { SearchMode } from "@/components/apx/navbar";
import { useListGalleryImages, useListFolders, useCreateFolder, useDeleteFolder, useListBatches, listFoldersKey } from "@/lib/api";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
} from "@/components/ui/dialog";
import { Images, FolderOpen, Plus, Layers, Trash2, Upload, X } from "lucide-react";
import { toast } from "sonner";

export const Route = createFileRoute("/")({
  component: GalleryPage,
});

// Unified image type from the API (GeneratedImageOut)
type GalleryImage = {
  id: number;
  batch_id: string;
  image_name: string | null;
  prompt: string | null;
  status: string | null;
  volume_path: string | null;
  variation_label: string | null;
  description: string | null;
  tags: string[];
  thumbnail_path: string | null;
};

function GalleryPage() {
  const [selectedFolder, setSelectedFolder] = useState<string | undefined>(undefined);
  const [selectedBatch, setSelectedBatch] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const PAGE_SIZE = 24;

  // After a fresh generate the backend writes the row in two phases (INSERT
  // image, UPDATE with evals). The Generate page sets `gallery-poll-until`
  // in sessionStorage so we poll the gallery for ~90s afterwards and pick
  // up the eval fields when they land — no manual refresh required.
  const [pollEnabled, setPollEnabled] = useState(() => {
    const until = Number(sessionStorage.getItem("gallery-poll-until") || 0);
    return Date.now() < until;
  });
  useEffect(() => {
    if (!pollEnabled) return;
    const until = Number(sessionStorage.getItem("gallery-poll-until") || 0);
    const remaining = until - Date.now();
    if (remaining <= 0) { setPollEnabled(false); return; }
    const t = setTimeout(() => {
      setPollEnabled(false);
      sessionStorage.removeItem("gallery-poll-until");
    }, remaining);
    return () => clearTimeout(t);
  }, [pollEnabled]);

  // Search state
  // `searchKind` distinguishes between text search ("Search: …"), upload-by-image
  // ("Similar to your-file.png"), and similar-to-an-existing-row ("Similar to <name>").
  const [searchQuery, setSearchQuery] = useState("");
  const [searchMode, setSearchMode] = useState<SearchMode>("semantic");
  const [searchKind, setSearchKind] = useState<"text" | "by-image" | "similar">("text");
  const [searchResults, setSearchResults] = useState<any[] | null>(null);
  const [searching, setSearching] = useState(false);

  // Pick up search from navbar (cross-page)
  useEffect(() => {
    const pending = sessionStorage.getItem("gallery-search");
    if (pending) {
      const pendingMode = (sessionStorage.getItem("gallery-search-mode") as SearchMode | null) ?? "semantic";
      sessionStorage.removeItem("gallery-search");
      sessionStorage.removeItem("gallery-search-mode");
      doSearch(pending, pendingMode);
    }
    const pendingSimilar = sessionStorage.getItem("gallery-similar-to");
    if (pendingSimilar) {
      sessionStorage.removeItem("gallery-similar-to");
      try {
        const { batch_id, id, label } = JSON.parse(pendingSimilar);
        doSearchSimilar(batch_id, id, label);
      } catch { /* ignore malformed */ }
    }
  }, []);

  const { data: foldersData } = useListFolders();
  const folders = foldersData?.data ?? [];

  const { data: batchesData } = useListBatches();
  const completedBatches = (batchesData?.data ?? []).filter((b: any) => b.status === "completed" && b.batch_mode !== "single" && b.batch_mode !== "edit");

  // Only show single/edit images in gallery (not batch images).
  // refetchOnMount/Focus so navigating here (or returning to the tab) after
  // a generate always pulls the latest rows. refetchInterval polls for ~90s
  // after a generate so eval fields appear without a manual refresh.
  const { data: galleryData, isLoading } = useListGalleryImages({
    params: {
      folder: selectedFolder,
      mode: "single",
      page,
      limit: PAGE_SIZE,
    },
    query: {
      refetchOnMount: "always",
      refetchOnWindowFocus: true,
      refetchInterval: pollEnabled ? 4000 : false,
    },
  });
  const items: GalleryImage[] = galleryData?.data ?? [];

  // We track only the (batch_id, id) of the open dialog. The full image data
  // is derived from items/searchResults on every render — that way refetches
  // (e.g. when the analyzer's Phase 2 UPDATE lands eval fields) flow into the
  // dialog automatically without a stale snapshot getting in the way.
  const [dialogRef, setDialogRef] = useState<{ batch_id: string; id: number } | null>(null);
  const dialogImage: ImageDialogImage | null = (() => {
    if (!dialogRef) return null;
    const pool: any[] = (searchResults ?? items) as any[];
    const fresh: any = pool.find((i: any) => i.batch_id === dialogRef.batch_id && (i.id ?? i.image_id) === dialogRef.id);
    if (!fresh) return null;
    return {
      id: fresh.id ?? fresh.image_id,
      batch_id: fresh.batch_id,
      image_name: fresh.image_name,
      prompt: fresh.prompt,
      status: fresh.status ?? "success",
      volume_path: fresh.volume_path,
      variation_label: fresh.variation_label,
      description: fresh.description,
      tags: fresh.tags ?? [],
      thumbnail_path: fresh.thumbnail_path,
      evaluation: fresh.evaluation,
      metrics: fresh.metrics,
      missing_elements: fresh.missing_elements ?? [],
      safety_flags: fresh.safety_flags ?? [],
      brand_conflicts: fresh.brand_conflicts ?? [],
      improved_prompt: fresh.improved_prompt,
      criteria_evaluation: fresh.criteria_evaluation,
    };
  })();
  const setDialogImage = (img: ImageDialogImage | null) =>
    setDialogRef(img ? { batch_id: img.batch_id, id: img.id } : null);
  const [newFolderName, setNewFolderName] = useState("");
  const [showNewFolder, setShowNewFolder] = useState(false);

  // Per-folder Import: hover-action triggers a hidden file picker; the chosen folder
  // is stashed in a ref so the change handler knows where to POST.
  const importInputRef = useRef<HTMLInputElement | null>(null);
  const importFolderRef = useRef<string>("default");
  const [importing, setImporting] = useState(false);
  const [importProgress, setImportProgress] = useState<{ current: number; total: number; name: string } | null>(null);
  const queryClient = useQueryClient();
  const createFolderMutation = useCreateFolder();
  const deleteFolderMutation = useDeleteFolder();
  const [folderToDelete, setFolderToDelete] = useState<{ name: string; image_count: number } | null>(null);

  const confirmDeleteFolder = () => {
    if (!folderToDelete) return;
    const target = folderToDelete;
    deleteFolderMutation.mutate(
      { params: { name: target.name } },
      {
        onSuccess: () => {
          queryClient.invalidateQueries({ queryKey: listFoldersKey() });
          queryClient.invalidateQueries({ queryKey: ["/api/gallery"] });
          if (selectedFolder === target.name) setSelectedFolder(undefined);
          toast.success(`Folder "${target.name}" deleted`);
          setFolderToDelete(null);
        },
        onError: (err) => toast.error(`Failed: ${err.message}`),
      }
    );
  };

  function handleFolderSelect(folder: string | undefined) {
    setSelectedFolder(folder);
    setSelectedBatch(null);
    setSearchResults(null);
    setSearchQuery("");
    setPage(1);
  }

  function handleBatchSelect(batchId: string) {
    setSelectedBatch(batchId);
    setSelectedFolder(undefined);
    setSearchResults(null);
    setSearchQuery("");
  }

  async function doSearch(q: string, mode: SearchMode = "semantic") {
    if (!q.trim()) { setSearchResults(null); setSearchQuery(""); setSearchKind("text"); return; }
    setSearchQuery(q);
    setSearchMode(mode);
    setSearchKind("text");
    setSearching(true);
    setSelectedFolder(undefined);
    setSelectedBatch(null);
    try {
      const res = await fetch(`/api/search?q=${encodeURIComponent(q.trim())}&mode=${mode}&limit=40`);
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setSearchResults(data.results ?? []);
    } catch (err) {
      toast.error(`Search failed: ${err}`);
    } finally {
      setSearching(false);
    }
  }

  async function doSearchByImage(file: File) {
    setSearchQuery(file.name);
    setSearchMode("semantic");
    setSearchKind("by-image");
    setSearching(true);
    setSelectedFolder(undefined);
    setSelectedBatch(null);
    try {
      const fd = new FormData();
      fd.append("image", file);
      const res = await fetch(`/api/search/by-image?limit=40`, { method: "POST", body: fd });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setSearchResults(data.results ?? []);
    } catch (err) {
      toast.error(`Image search failed: ${err}`);
    } finally {
      setSearching(false);
    }
  }

  async function doSearchSimilar(batch_id: string, id: number, label?: string) {
    setSearchQuery(label ?? `${batch_id}/${id}`);
    setSearchMode("semantic");
    setSearchKind("similar");
    setSearching(true);
    setSelectedFolder(undefined);
    setSelectedBatch(null);
    try {
      const res = await fetch(`/api/search/similar/${batch_id}/${id}?limit=40`);
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setSearchResults(data.results ?? []);
    } catch (err) {
      toast.error(`Similar search failed: ${err}`);
    } finally {
      setSearching(false);
    }
  }

  function clearSearch() {
    setSearchResults(null);
    setSearchQuery("");
    setSearchKind("text");
  }

  function triggerImport(folderName: string) {
    importFolderRef.current = folderName;
    importInputRef.current?.click();
  }

  async function handleImportFiles(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? []);
    if (importInputRef.current) importInputRef.current.value = ""; // allow re-importing same files later
    if (files.length === 0) return;
    const targetFolder = importFolderRef.current;

    setImporting(true);
    setImportProgress({ current: 0, total: files.length, name: files[0].name });
    try {
      const fd = new FormData();
      fd.set("folder", targetFolder);
      for (const f of files) fd.append("images", f);

      const res = await fetch(`/api/import`, { method: "POST", body: fd });
      if (!res.ok || !res.body) throw new Error(await res.text());

      // Stream the SSE-like response and parse `event:`/`data:` lines.
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let idx;
        while ((idx = buffer.indexOf("\n\n")) >= 0) {
          const block = buffer.slice(0, idx);
          buffer = buffer.slice(idx + 2);
          let event = "message";
          let dataLine = "";
          for (const line of block.split("\n")) {
            if (line.startsWith("event: ")) event = line.slice(7).trim();
            else if (line.startsWith("data: ")) dataLine += line.slice(6);
          }
          if (!dataLine) continue;
          try {
            const data = JSON.parse(dataLine);
            if (event === "progress") {
              setImportProgress({ current: data.index, total: data.total, name: data.name });
            } else if (event === "complete") {
              toast.success(`Imported ${data.count} image${data.count === 1 ? "" : "s"} into "${targetFolder}" — analysis running…`);
              // Poll the gallery for ~120s so eval/embedding fields appear as Phase 2 lands.
              sessionStorage.setItem("gallery-poll-until", String(Date.now() + 120_000));
              setPollEnabled(true);
            } else if (event === "error") {
              toast.error(`Import failed for ${data.name}: ${data.error}`);
            }
          } catch { /* ignore non-JSON keep-alives */ }
        }
      }

      queryClient.invalidateQueries({ queryKey: listFoldersKey() });
      queryClient.invalidateQueries({ queryKey: ["/api/gallery"] });
      // Switch to the target folder so the user sees the new rows.
      setSelectedFolder(targetFolder);
      setSelectedBatch(null);
    } catch (err) {
      toast.error(`Import failed: ${err}`);
    } finally {
      setImporting(false);
      setImportProgress(null);
    }
  }


  function imageSrc(img: GalleryImage): string {
    return `/api/batch-images/${img.batch_id}/${img.image_name}_generated.jpeg`;
  }

  function thumbnailSrc(img: GalleryImage): string {
    if (img.thumbnail_path) {
      return `/api/gallery/${img.batch_id}/${img.id}/thumbnail`;
    }
    return imageSrc(img);
  }

  // Determine what to display
  const displayItems: GalleryImage[] = searchResults ?? items;
  const title = searchResults
    ? (searchKind === "text"
        ? `Search: "${searchQuery}"`
        : `Similar to: ${searchQuery}`)
    : selectedFolder
    ? selectedFolder
    : "Gallery";

  return (
    <div className="min-h-screen bg-background flex flex-col">
      <input
        ref={importInputRef}
        type="file"
        accept="image/png,image/jpeg,image/jpg,image/webp"
        multiple
        className="hidden"
        onChange={handleImportFiles}
      />
      <Navbar searchQuery={searchQuery} searchMode={searchMode} onSearch={doSearch} onSearchByImage={doSearchByImage} />
      <div className="flex flex-1">
        {/* Sidebar */}
        <aside className="w-56 shrink-0 border-r p-4 hidden md:block">
          <h2 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-3">Folders</h2>
          <div className="space-y-1">
            <button
              onClick={() => handleFolderSelect(undefined)}
              className={`w-full text-left flex items-center gap-2 px-3 py-2 rounded-md text-sm transition-colors ${!selectedFolder && !selectedBatch && !searchResults ? "bg-primary text-primary-foreground" : "hover:bg-muted"}`}
            >
              <Images className="h-4 w-4 shrink-0" />
              <span className="truncate">All Images</span>
            </button>
            {folders.map((folder) => (
              <div key={folder.name} className="group/folder relative flex items-center">
                <button
                  onClick={() => handleFolderSelect(folder.name)}
                  className={`w-full text-left flex items-center gap-2 px-3 py-2 rounded-md text-sm transition-colors ${selectedFolder === folder.name ? "bg-primary text-primary-foreground" : "hover:bg-muted"}`}
                >
                  <FolderOpen className="h-4 w-4 shrink-0" />
                  <span className="truncate">{folder.name}</span>
                  <span className="ml-auto text-xs opacity-60 group-hover/folder:hidden">{folder.image_count}</span>
                </button>
                <button
                  className={`absolute ${folder.name !== "default" ? "right-9" : "right-2"} hidden group-hover/folder:flex items-center justify-center h-6 w-6 rounded hover:bg-primary/20 text-muted-foreground hover:text-primary transition-colors`}
                  title="Import images into this folder"
                  onClick={(e) => { e.stopPropagation(); triggerImport(folder.name); }}
                  disabled={importing}
                >
                  <Upload className="h-3.5 w-3.5" />
                </button>
                {folder.name !== "default" && (
                  <button
                    className="absolute right-2 hidden group-hover/folder:flex items-center justify-center h-6 w-6 rounded hover:bg-destructive/20 text-muted-foreground hover:text-destructive transition-colors"
                    title="Delete folder"
                    onClick={(e) => {
                      e.stopPropagation();
                      setFolderToDelete({ name: folder.name, image_count: folder.image_count ?? 0 });
                    }}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>
            ))}
            {showNewFolder ? (
              <form
                className="flex gap-1 mt-1"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (!newFolderName.trim()) return;
                  createFolderMutation.mutate(
                    { name: newFolderName.trim() },
                    {
                      onSuccess: () => {
                        queryClient.invalidateQueries({ queryKey: listFoldersKey() });
                        setNewFolderName("");
                        setShowNewFolder(false);
                        toast.success("Folder created");
                      },
                      onError: (err) => toast.error(`Failed: ${err.message}`),
                    }
                  );
                }}
              >
                <input
                  autoFocus
                  className="flex-1 min-w-0 px-2 py-1 text-sm border rounded-md bg-background"
                  placeholder="Folder name"
                  value={newFolderName}
                  onChange={(e) => setNewFolderName(e.target.value)}
                  onKeyDown={(e) => e.key === "Escape" && setShowNewFolder(false)}
                />
                <Button type="submit" size="sm" variant="ghost" className="h-7 w-7 p-0 shrink-0">
                  <Plus className="h-3 w-3" />
                </Button>
              </form>
            ) : (
              <button
                onClick={() => setShowNewFolder(true)}
                className="w-full text-left flex items-center gap-2 px-3 py-2 rounded-md text-sm text-muted-foreground hover:bg-muted transition-colors mt-1"
              >
                <Plus className="h-4 w-4 shrink-0" />
                <span>New Folder</span>
              </button>
            )}
          </div>

          {/* Batch runs */}
          {completedBatches.length > 0 && (
            <>
              <h2 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-3 mt-6">Batch Runs</h2>
              <div className="space-y-1">
                {completedBatches.map((batch: any) => (
                  <button
                    key={batch.batch_id}
                    onClick={() => handleBatchSelect(batch.batch_id)}
                    className={`w-full text-left flex items-center gap-2 px-3 py-2 rounded-md text-sm transition-colors ${selectedBatch === batch.batch_id ? "bg-primary text-primary-foreground" : "hover:bg-muted"}`}
                  >
                    <Layers className="h-4 w-4 shrink-0" />
                    <span className="truncate">{batch.batch_name || batch.batch_id}</span>
                    <span className="ml-auto text-xs opacity-60">{batch.successful_images ?? 0}</span>
                  </button>
                ))}
              </div>
            </>
          )}
        </aside>

        {/* Main content */}
        <main className="flex-1 p-6 overflow-y-auto">
          {selectedBatch ? (
            /* Batch detail view — inline with sidebar */
            <BatchDetailContent
              batchId={selectedBatch}
              onDeleted={() => { setSelectedBatch(null); }}
            />
          ) : (
          <>
          {/* Search + title */}
          <div className="mb-6 flex items-start justify-between gap-4">
            <div>
              <h1 className="text-2xl font-bold">{title}</h1>
              <p className="text-sm text-muted-foreground mt-0.5">
                {displayItems.length} image{displayItems.length !== 1 ? "s" : ""}
                {searchResults && searchKind === "text" && (
                  <span className="ml-2 text-xs uppercase tracking-wide opacity-70">{searchMode === "semantic" ? "Semantic" : "Text"}</span>
                )}
              </p>
            </div>
            <div className="flex items-center gap-2">
              {importing && importProgress && (
                <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground border rounded-md px-2 py-1 bg-muted/30">
                  <Upload className="h-3 w-3 animate-pulse" />
                  Importing {importProgress.current}/{importProgress.total}
                  <span className="hidden sm:inline opacity-70">— {importProgress.name}</span>
                </span>
              )}
              {searchResults && (
                <button
                  onClick={clearSearch}
                  className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground border rounded-md px-2 py-1 hover:bg-muted/50"
                >
                  <X className="h-3 w-3" /> Clear search
                </button>
              )}
            </div>
          </div>

          {/* Image grid */}
          {isLoading && !searchResults ? (
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
              {Array.from({ length: 12 }).map((_, i) => <Skeleton key={i} className="aspect-square rounded-lg" />)}
            </div>
          ) : displayItems.length === 0 ? (
            <div className="text-center py-24 border rounded-lg">
              <Images className="h-12 w-12 mx-auto text-muted-foreground mb-4" />
              <h3 className="text-lg font-medium">{searchResults ? "No results found" : "No images yet"}</h3>
              <p className="text-muted-foreground mt-1">
                {searchResults ? "Try a different search term" : "Generate images using the Generate tab"}
              </p>
            </div>
          ) : (
            <>
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
                {displayItems.map((img: any) => (
                  <div
                    key={`${img.batch_id}-${img.id ?? img.image_id}`}
                    className="group relative overflow-hidden rounded-lg border cursor-pointer hover:ring-2 hover:ring-primary transition-all aspect-square bg-muted"
                    onClick={() => setDialogImage({
                      id: img.id ?? img.image_id,
                      batch_id: img.batch_id,
                      image_name: img.image_name,
                      prompt: img.prompt,
                      status: img.status ?? "success",
                      volume_path: img.volume_path,
                      variation_label: img.variation_label,
                      description: img.description,
                      tags: img.tags ?? [],
                      thumbnail_path: img.thumbnail_path,
                      evaluation: img.evaluation,
                      metrics: img.metrics,
                      missing_elements: img.missing_elements ?? [],
                      safety_flags: img.safety_flags ?? [],
                      brand_conflicts: img.brand_conflicts ?? [],
                      improved_prompt: img.improved_prompt,
                      criteria_evaluation: img.criteria_evaluation,
                    })}
                  >
                    <img
                      src={img.thumbnail_path ? `/api/gallery/${img.batch_id}/${img.id ?? img.image_id}/thumbnail` : `/api/batch-images/${img.batch_id}/${img.image_name}_generated.jpeg`}
                      alt={img.image_name ?? ""}
                      className="w-full h-full object-cover"
                      loading="lazy"
                      onError={(e) => {
                        (e.target as HTMLImageElement).src = `/api/batch-images/${img.batch_id}/${img.image_name}_generated.jpeg`;
                      }}
                    />
                    <div className="absolute inset-0 bg-black/0 group-hover:bg-black/40 transition-colors" />
                    {searchResults && typeof img.score === "number" && (
                      <div
                        className="absolute top-1.5 right-1.5 px-1.5 py-0.5 rounded-md bg-black/60 text-white text-[10px] font-mono tabular-nums backdrop-blur-sm"
                        title={`Similarity ${img.score.toFixed(3)}`}
                      >
                        {img.score.toFixed(2)}
                      </div>
                    )}
                    <div className="absolute bottom-0 left-0 right-0 p-2 translate-y-full group-hover:translate-y-0 transition-transform">
                      <p className="text-white text-xs font-medium truncate">{img.prompt}</p>
                      {(img.tags ?? []).length > 0 && (
                        <div className="flex gap-1 mt-1 flex-wrap">
                          {(img.tags ?? []).slice(0, 3).map((tag: string) => (
                            <span key={tag} className="text-[10px] bg-white/20 text-white px-1 py-0.5 rounded">{tag}</span>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>

              {/* Pagination (only for non-search views) */}
              {!searchResults && items.length === PAGE_SIZE && (
                <div className="flex items-center justify-center gap-2 mt-8">
                  <Button variant="outline" size="sm" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page === 1}>
                    Previous
                  </Button>
                  <span className="text-sm text-muted-foreground">Page {page}</span>
                  <Button variant="outline" size="sm" onClick={() => setPage((p) => p + 1)} disabled={items.length < PAGE_SIZE}>
                    Next
                  </Button>
                </div>
              )}
            </>
          )}
          </>
          )}
        </main>
      </div>

      <ImageDialog
        image={dialogImage}
        open={!!dialogImage}
        onClose={() => setDialogImage(null)}
        onFindSimilar={(img) => {
          setDialogRef(null);
          doSearchSimilar(img.batch_id, img.id, img.image_name ?? `${img.batch_id}/${img.id}`);
        }}
      />

      <Dialog open={folderToDelete !== null} onOpenChange={(o) => !o && !deleteFolderMutation.isPending && setFolderToDelete(null)}>
        <DialogContent>
          <DialogTitle>Delete folder "{folderToDelete?.name}"?</DialogTitle>
          <DialogDescription>
            {folderToDelete?.image_count
              ? `This will permanently delete the folder and all ${folderToDelete.image_count} image${folderToDelete.image_count === 1 ? "" : "s"} in it (database rows + Volume files). Cannot be undone.`
              : "This will permanently delete the folder. Cannot be undone."}
          </DialogDescription>
          <DialogFooter>
            <Button variant="outline" onClick={() => setFolderToDelete(null)} disabled={deleteFolderMutation.isPending}>Cancel</Button>
            <Button variant="destructive" className="text-white" onClick={confirmDeleteFolder} disabled={deleteFolderMutation.isPending}>
              {deleteFolderMutation.isPending ? "Deleting..." : "Delete"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
