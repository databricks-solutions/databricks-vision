import { useQuery } from "@tanstack/react-query";
import type { UseQueryOptions } from "@tanstack/react-query";
import { ApiError } from "./api";

// --- Types ---

export interface CatalogOut {
  name: string;
  comment?: string | null;
}

export interface SchemaOut {
  name: string;
  comment?: string | null;
}

export interface VolumeOut {
  name: string;
  full_name: string;
  volume_type?: string | null;
}

export interface FileEntryOut {
  name: string;
  path: string;
  is_directory: boolean;
  file_size?: number | null;
}

// --- Fetch functions ---

async function fetchJson<T>(url: string): Promise<{ data: T }> {
  const res = await fetch(url);
  if (!res.ok) {
    const body = await res.text();
    let parsed: unknown;
    try {
      parsed = JSON.parse(body);
    } catch {
      parsed = body;
    }
    throw new ApiError(res.status, res.statusText, parsed);
  }
  return { data: await res.json() };
}

export const listCatalogs = () =>
  fetchJson<CatalogOut[]>("/api/volumes/catalogs");

export const listSchemas = (catalog: string) =>
  fetchJson<SchemaOut[]>(`/api/volumes/catalogs/${encodeURIComponent(catalog)}/schemas`);

export const listVolumes = (catalog: string, schema: string) =>
  fetchJson<VolumeOut[]>(
    `/api/volumes/catalogs/${encodeURIComponent(catalog)}/schemas/${encodeURIComponent(schema)}/volumes`
  );

export const browseVolumeFiles = (path: string) =>
  fetchJson<FileEntryOut[]>(`/api/volumes/browse?path=${encodeURIComponent(path)}`);

// --- Query hooks ---

const FIVE_MINUTES = 5 * 60 * 1000;

export function useListCatalogs<TData = { data: CatalogOut[] }>(options?: {
  query?: Omit<UseQueryOptions<{ data: CatalogOut[] }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
  return useQuery({
    queryKey: ["/api/volumes/catalogs"] as const,
    queryFn: () => listCatalogs(),
    staleTime: FIVE_MINUTES,
    retry: 1,
    ...options?.query,
  });
}

export function useListSchemas<TData = { data: SchemaOut[] }>(options?: {
  catalog?: string | null;
  query?: Omit<UseQueryOptions<{ data: SchemaOut[] }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
  return useQuery({
    queryKey: ["/api/volumes/schemas", { catalog: options?.catalog }] as const,
    queryFn: () => listSchemas(options!.catalog!),
    enabled: !!options?.catalog,
    staleTime: FIVE_MINUTES,
    retry: 1,
    ...options?.query,
  });
}

export function useListVolumes<TData = { data: VolumeOut[] }>(options?: {
  catalog?: string | null;
  schema?: string | null;
  query?: Omit<UseQueryOptions<{ data: VolumeOut[] }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
  return useQuery({
    queryKey: ["/api/volumes/volumes", { catalog: options?.catalog, schema: options?.schema }] as const,
    queryFn: () => listVolumes(options!.catalog!, options!.schema!),
    enabled: !!options?.catalog && !!options?.schema,
    staleTime: FIVE_MINUTES,
    retry: 1,
    ...options?.query,
  });
}

export function useBrowseVolumeFiles<TData = { data: FileEntryOut[] }>(options?: {
  path?: string | null;
  query?: Omit<UseQueryOptions<{ data: FileEntryOut[] }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
  return useQuery({
    queryKey: ["/api/volumes/browse", { path: options?.path }] as const,
    queryFn: () => browseVolumeFiles(options!.path!),
    enabled: !!options?.path,
    staleTime: FIVE_MINUTES,
    retry: 1,
    ...options?.query,
  });
}
