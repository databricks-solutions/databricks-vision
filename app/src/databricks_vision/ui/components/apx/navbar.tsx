import { ReactNode, useRef, useState } from "react";
import { Link, useNavigate } from "@tanstack/react-router";
import { Eye, Images, Sparkles, Search, X, ImagePlus, Settings as SettingsIcon } from "lucide-react";

export type SearchMode = "semantic" | "fts";

interface NavbarProps {
  leftContent?: ReactNode;
  rightContent?: ReactNode;
  searchQuery?: string;
  searchMode?: SearchMode;
  onSearch?: (query: string, mode: SearchMode) => void;
  onSearchByImage?: (file: File) => void;
}

export function Navbar({ leftContent, rightContent, searchQuery: externalQuery, searchMode: externalMode, onSearch, onSearchByImage }: NavbarProps) {
  const navigate = useNavigate();
  const [query, setQuery] = useState(externalQuery ?? "");
  const [mode, setMode] = useState<SearchMode>(externalMode ?? "semantic");
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;
    if (onSearch) {
      onSearch(query.trim(), mode);
    } else {
      // Navigate to gallery with search — store in sessionStorage for the gallery to pick up
      sessionStorage.setItem("gallery-search", query.trim());
      sessionStorage.setItem("gallery-search-mode", mode);
      navigate({ to: "/" });
    }
  };

  const handleClear = () => {
    setQuery("");
    onSearch?.("", mode);
  };

  const handleImagePicked = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file && onSearchByImage) onSearchByImage(file);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  return (
    <header className="z-50 bg-background/80 backdrop-blur-sm border-b">
      <div className="h-16 flex items-center px-4 gap-6">
        {leftContent || (
          <Link to="/" className="flex items-center gap-2 font-semibold shrink-0">
            <Eye className="h-5 w-5" />
            Databricks Vision
          </Link>
        )}
        <nav className="flex items-center gap-1">
          <Link
            to="/"
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors [&.active]:text-foreground [&.active]:font-medium"
          >
            <Images className="h-4 w-4" />
            Gallery
          </Link>
          <Link
            to="/generate"
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors [&.active]:text-foreground [&.active]:font-medium"
          >
            <Sparkles className="h-4 w-4" />
            Generate
          </Link>
          <Link
            to="/settings"
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors [&.active]:text-foreground [&.active]:font-medium"
          >
            <SettingsIcon className="h-4 w-4" />
            Settings
          </Link>
        </nav>
        <div className="flex-1" />
        <form onSubmit={handleSubmit} className="flex items-center gap-1">
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <input
              className="pl-8 pr-24 py-1.5 text-sm border rounded-md bg-background w-64 focus:w-80 transition-all"
              placeholder={mode === "semantic" ? "Search images by meaning..." : "Search images (text)..."}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <select
              value={mode}
              onChange={(e) => setMode(e.target.value as SearchMode)}
              className="absolute right-7 top-1/2 -translate-y-1/2 h-6 text-[11px] bg-transparent text-muted-foreground hover:text-foreground border-0 outline-none cursor-pointer pr-1 appearance-none"
              title="Search mode"
            >
              <option value="semantic">Semantic</option>
              <option value="fts">Text</option>
            </select>
            {query && (
              <button type="button" onClick={handleClear} className="absolute right-2 top-1/2 -translate-y-1/2">
                <X className="h-3.5 w-3.5 text-muted-foreground hover:text-foreground" />
              </button>
            )}
          </div>
          {onSearchByImage && (
            <>
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                className="ml-1 inline-flex items-center justify-center h-8 w-8 rounded-md border bg-background text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
                title="Search by image (similarity)"
              >
                <ImagePlus className="h-4 w-4" />
              </button>
              <input ref={fileInputRef} type="file" accept="image/*" className="hidden" onChange={handleImagePicked} />
            </>
          )}
        </form>
        {rightContent}
      </div>
    </header>
  );
}

export default Navbar;
