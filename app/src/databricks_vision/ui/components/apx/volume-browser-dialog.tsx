import { useState, useCallback } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Database,
  Folder,
  FileImage,
  File,
  ChevronRight,
  FolderOpen,
  AlertCircle,
} from "lucide-react";
import {
  useListCatalogs,
  useListSchemas,
  useListVolumes,
  useBrowseVolumeFiles,
} from "@/lib/volumes-api";

interface VolumeBrowserDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSelect: (path: string) => void;
  mode: "file" | "directory";
  fileFilter?: string[];
}

type BreadcrumbSegment = { label: string; level: number };

const IMAGE_EXTENSIONS = [".png", ".jpg", ".jpeg", ".webp"];

function matchesFilter(name: string, filter?: string[]): boolean {
  const exts = filter ?? IMAGE_EXTENSIONS;
  const lower = name.toLowerCase();
  return exts.some((ext) => lower.endsWith(ext));
}

export default function VolumeBrowserDialog({
  open,
  onOpenChange,
  onSelect,
  mode,
  fileFilter,
}: VolumeBrowserDialogProps) {
  const [catalog, setCatalog] = useState<string | null>(null);
  const [schema, setSchema] = useState<string | null>(null);
  const [volume, setVolume] = useState<string | null>(null);
  const [browsePath, setBrowsePath] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);

  const level =
    browsePath != null ? 3 : volume != null ? 3 : schema != null ? 2 : catalog != null ? 1 : 0;

  const catalogsQuery = useListCatalogs({ query: { enabled: open } });
  const schemasQuery = useListSchemas({ catalog, query: { enabled: open && !!catalog } });
  const volumesQuery = useListVolumes({ catalog, schema, query: { enabled: open && !!catalog && !!schema } });
  const filesQuery = useBrowseVolumeFiles({
    path: browsePath,
    query: { enabled: open && !!browsePath },
  });

  const reset = useCallback(() => {
    setCatalog(null);
    setSchema(null);
    setVolume(null);
    setBrowsePath(null);
    setSelectedFile(null);
  }, []);

  const handleOpenChange = useCallback(
    (o: boolean) => {
      if (!o) reset();
      onOpenChange(o);
    },
    [onOpenChange, reset]
  );

  const navigateToCatalog = (name: string) => {
    setCatalog(name);
    setSchema(null);
    setVolume(null);
    setBrowsePath(null);
    setSelectedFile(null);
  };

  const navigateToSchema = (name: string) => {
    setSchema(name);
    setVolume(null);
    setBrowsePath(null);
    setSelectedFile(null);
  };

  const navigateToVolume = (name: string) => {
    setVolume(name);
    const path = `/Volumes/${catalog}/${schema}/${name}`;
    setBrowsePath(path);
    setSelectedFile(null);
  };

  const navigateToFolder = (path: string) => {
    setBrowsePath(path);
    setSelectedFile(null);
  };

  const handleBreadcrumbClick = (targetLevel: number) => {
    if (targetLevel === 0) reset();
    else if (targetLevel === 1) {
      setSchema(null);
      setVolume(null);
      setBrowsePath(null);
      setSelectedFile(null);
    } else if (targetLevel === 2) {
      setVolume(null);
      setBrowsePath(null);
      setSelectedFile(null);
    } else if (targetLevel === 3 && volume) {
      const path = `/Volumes/${catalog}/${schema}/${volume}`;
      setBrowsePath(path);
      setSelectedFile(null);
    }
  };

  const handleSelect = () => {
    if (mode === "directory" && browsePath) {
      onSelect(browsePath);
      handleOpenChange(false);
    } else if (mode === "file" && selectedFile) {
      onSelect(selectedFile);
      handleOpenChange(false);
    }
  };

  // Build breadcrumbs
  const breadcrumbs: BreadcrumbSegment[] = [{ label: "Catalogs", level: 0 }];
  if (catalog) breadcrumbs.push({ label: catalog, level: 1 });
  if (schema) breadcrumbs.push({ label: schema, level: 2 });
  if (volume) {
    breadcrumbs.push({ label: volume, level: 3 });
    // Add subfolder segments if browsing deeper than the volume root
    if (browsePath) {
      const volumeRoot = `/Volumes/${catalog}/${schema}/${volume}`;
      const suffix = browsePath.slice(volumeRoot.length);
      if (suffix) {
        const parts = suffix.split("/").filter(Boolean);
        // Show subfolder segments (they all navigate within level 3)
        parts.forEach((part) => {
          breadcrumbs.push({ label: part, level: -1 }); // -1 = non-clickable deep path
        });
      }
    }
  }

  const canSelect =
    (mode === "directory" && browsePath != null) ||
    (mode === "file" && selectedFile != null);

  const isLoading =
    (level === 0 && catalogsQuery.isLoading) ||
    (level === 1 && schemasQuery.isLoading) ||
    (level === 2 && volumesQuery.isLoading) ||
    (level === 3 && filesQuery.isLoading);

  const error =
    (level === 0 && catalogsQuery.error) ||
    (level === 1 && schemasQuery.error) ||
    (level === 2 && volumesQuery.error) ||
    (level === 3 && filesQuery.error);

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FolderOpen className="h-5 w-5" />
            Browse Volumes
          </DialogTitle>
          <DialogDescription>
            {mode === "directory"
              ? "Select a folder from Unity Catalog Volumes"
              : "Select a file from Unity Catalog Volumes"}
          </DialogDescription>
        </DialogHeader>

        {/* Breadcrumbs */}
        <div className="flex items-center gap-1 text-sm flex-wrap">
          {breadcrumbs.map((b, i) => (
            <span key={i} className="flex items-center gap-1">
              {i > 0 && <ChevronRight className="h-3 w-3 text-muted-foreground shrink-0" />}
              {b.level >= 0 && i < breadcrumbs.length - 1 ? (
                <button
                  type="button"
                  className="text-muted-foreground hover:text-foreground transition-colors"
                  onClick={() => handleBreadcrumbClick(b.level)}
                >
                  {b.label}
                </button>
              ) : (
                <span className="font-medium">{b.label}</span>
              )}
            </span>
          ))}
        </div>

        {/* List */}
        <div className="border rounded-lg overflow-hidden">
          <div className="max-h-72 overflow-y-auto divide-y">
            {isLoading && (
              <div className="p-3 space-y-2">
                {[...Array(5)].map((_, i) => (
                  <Skeleton key={i} className="h-8 w-full" />
                ))}
              </div>
            )}

            {error && (
              <div className="p-4 flex items-center gap-2 text-sm text-destructive">
                <AlertCircle className="h-4 w-4 shrink-0" />
                <span>Failed to load: {(error as Error).message}</span>
              </div>
            )}

            {!isLoading && !error && level === 0 && (
              <>
                {catalogsQuery.data?.data.length === 0 && (
                  <div className="p-4 text-sm text-muted-foreground text-center">
                    No catalogs found
                  </div>
                )}
                {catalogsQuery.data?.data.map((c) => (
                  <button
                    key={c.name}
                    type="button"
                    className="w-full flex items-center gap-3 px-3 py-2.5 hover:bg-muted/50 transition-colors text-left"
                    onClick={() => navigateToCatalog(c.name)}
                  >
                    <Database className="h-4 w-4 text-muted-foreground shrink-0" />
                    <span className="flex-1 text-sm truncate">{c.name}</span>
                    <ChevronRight className="h-4 w-4 text-muted-foreground shrink-0" />
                  </button>
                ))}
              </>
            )}

            {!isLoading && !error && level === 1 && (
              <>
                {schemasQuery.data?.data.length === 0 && (
                  <div className="p-4 text-sm text-muted-foreground text-center">
                    No schemas found
                  </div>
                )}
                {schemasQuery.data?.data.map((s) => (
                  <button
                    key={s.name}
                    type="button"
                    className="w-full flex items-center gap-3 px-3 py-2.5 hover:bg-muted/50 transition-colors text-left"
                    onClick={() => navigateToSchema(s.name)}
                  >
                    <Folder className="h-4 w-4 text-muted-foreground shrink-0" />
                    <span className="flex-1 text-sm truncate">{s.name}</span>
                    <ChevronRight className="h-4 w-4 text-muted-foreground shrink-0" />
                  </button>
                ))}
              </>
            )}

            {!isLoading && !error && level === 2 && (
              <>
                {volumesQuery.data?.data.length === 0 && (
                  <div className="p-4 text-sm text-muted-foreground text-center">
                    No volumes found
                  </div>
                )}
                {volumesQuery.data?.data.map((v) => (
                  <button
                    key={v.name}
                    type="button"
                    className="w-full flex items-center gap-3 px-3 py-2.5 hover:bg-muted/50 transition-colors text-left"
                    onClick={() => navigateToVolume(v.name)}
                  >
                    <Folder className="h-4 w-4 text-muted-foreground shrink-0" />
                    <span className="flex-1 text-sm truncate">{v.name}</span>
                    {v.volume_type && (
                      <span className="text-xs text-muted-foreground">{v.volume_type}</span>
                    )}
                    <ChevronRight className="h-4 w-4 text-muted-foreground shrink-0" />
                  </button>
                ))}
              </>
            )}

            {!isLoading && !error && level === 3 && (
              <>
                {filesQuery.data?.data.length === 0 && (
                  <div className="p-4 text-sm text-muted-foreground text-center">
                    Empty folder
                  </div>
                )}
                {filesQuery.data?.data
                  .sort((a, b) => {
                    // Directories first, then files
                    if (a.is_directory && !b.is_directory) return -1;
                    if (!a.is_directory && b.is_directory) return 1;
                    return a.name.localeCompare(b.name);
                  })
                  .map((entry) => {
                    const isImage = !entry.is_directory && matchesFilter(entry.name, fileFilter);
                    const isSelectable =
                      entry.is_directory || (mode === "file" && isImage);
                    const isSelected = selectedFile === entry.path;
                    const isDimmed = mode === "file" && !entry.is_directory && !isImage;

                    return (
                      <button
                        key={entry.path}
                        type="button"
                        className={`w-full flex items-center gap-3 px-3 py-2.5 transition-colors text-left ${
                          isSelected
                            ? "bg-primary/10"
                            : isDimmed
                              ? "opacity-40 cursor-default"
                              : "hover:bg-muted/50"
                        }`}
                        onClick={() => {
                          if (entry.is_directory) {
                            navigateToFolder(entry.path);
                          } else if (mode === "file" && isImage) {
                            setSelectedFile(entry.path);
                          }
                        }}
                        disabled={isDimmed}
                      >
                        {entry.is_directory ? (
                          <Folder className="h-4 w-4 text-muted-foreground shrink-0" />
                        ) : isImage ? (
                          <FileImage className="h-4 w-4 text-muted-foreground shrink-0" />
                        ) : (
                          <File className="h-4 w-4 text-muted-foreground shrink-0" />
                        )}
                        <span className="flex-1 text-sm truncate">{entry.name}</span>
                        {entry.is_directory && (
                          <ChevronRight className="h-4 w-4 text-muted-foreground shrink-0" />
                        )}
                        {entry.file_size != null && !entry.is_directory && (
                          <span className="text-xs text-muted-foreground">
                            {formatFileSize(entry.file_size)}
                          </span>
                        )}
                      </button>
                    );
                  })}
              </>
            )}
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => handleOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={handleSelect} disabled={!canSelect}>
            {mode === "directory" ? "Select Folder" : "Select File"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
