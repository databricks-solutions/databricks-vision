import { useQuery, useSuspenseQuery, useMutation } from "@tanstack/react-query";
import type { UseQueryOptions, UseSuspenseQueryOptions, UseMutationOptions } from "@tanstack/react-query";
export class ApiError extends Error {
    status: number;
    statusText: string;
    body: unknown;
    constructor(status: number, statusText: string, body: unknown){
        super(`HTTP ${status}: ${statusText}`);
        this.name = "ApiError";
        this.status = status;
        this.statusText = statusText;
        this.body = body;
    }
}
export interface AppConfigOut {
    org_id?: string;
    workspace_url: string;
}
export interface BatchCreate {
    background?: string;
    batch_mode?: string;
    batch_name?: string;
    image_model?: string;
    input_volume_path?: string;
    output_format?: string;
    prompt_template?: string;
    quality?: string;
    reference_image_path?: string;
    size?: string;
    source_image_path?: string;
    style_guideline_id?: number | null;
    variations?: VariationItem[];
}
export interface BatchDetailOut {
    batch: BatchRunOut;
    images: GeneratedImageOut[];
}
export interface BatchRunOut {
    background?: string | null;
    batch_id: string;
    batch_mode?: string;
    batch_name?: string | null;
    created_at?: string | null;
    created_by?: string | null;
    folder?: string;
    image_model?: string | null;
    input_volume_path: string;
    job_run_id?: number | null;
    output_format?: string | null;
    output_volume_path?: string | null;
    prompt_template?: string | null;
    quality?: string | null;
    reference_image_path?: string | null;
    size?: string | null;
    source_image_path?: string | null;
    status: string;
    style_guideline_id?: number | null;
    successful_images?: number | null;
    total_images?: number | null;
}
export interface Body_analyzeGalleryImages {
    batch_id: string;
}
export interface Body_editImages {
    background?: string;
    folder?: string;
    images?: string[];
    input_fidelity?: string;
    n?: number;
    output_format?: string;
    prompt: string;
    quality?: string;
    size?: string;
    source_batch_id?: string | null;
    source_image_id?: number | null;
}
export interface Body_generateImages {
    background?: string;
    criteria?: string;
    folder?: string;
    n?: number;
    output_format?: string;
    prompt: string;
    quality?: string;
    size?: string;
}
export interface Body_importImages {
    folder?: string;
    images?: string[];
}
export interface Body_rewritePrompt {
    images?: string[];
    instructions?: string;
    prompt?: string;
}
export interface Body_searchByImage {
    image: string;
}
export interface CatalogOut {
    comment?: string | null;
    name: string;
}
export interface ComplexValue {
    display?: string | null;
    primary?: boolean | null;
    ref?: string | null;
    type?: string | null;
    value?: string | null;
}
export interface FileEntryOut {
    file_size?: number | null;
    is_directory: boolean;
    name: string;
    path: string;
}
export interface FolderCreate {
    name: string;
}
export interface FolderOut {
    created_at?: string | null;
    id: string;
    image_count?: number;
    name: string;
}
export interface GeneratedImageOut {
    batch_id: string;
    brand_conflicts?: string[];
    criteria_evaluation?: string | null;
    description?: string | null;
    error_message?: string | null;
    evaluation?: string | null;
    folder?: string | null;
    id?: number | null;
    image_name?: string | null;
    improved_prompt?: string | null;
    input_image_path?: string | null;
    metrics?: Record<string, unknown> | null;
    missing_elements?: string[];
    prompt?: string | null;
    safety_flags?: string[];
    status?: string | null;
    tags?: string[];
    thumbnail_path?: string | null;
    variation_label?: string | null;
    version_count?: number;
    volume_path?: string | null;
}
export interface HTTPValidationError {
    detail?: ValidationError[];
}
export interface ImageVersionOut {
    batch_id: string;
    created_at?: string | null;
    error_message?: string | null;
    image_id: number;
    prompt: string;
    status?: string | null;
    version: number;
    version_id: number;
    volume_path?: string | null;
}
export interface Name {
    family_name?: string | null;
    given_name?: string | null;
}
export interface RegenerateRequest {
    prompt: string;
    use_source?: boolean;
}
export interface RegenerateResponse {
    image: GeneratedImageOut;
    version: ImageVersionOut;
}
export interface SchemaOut {
    comment?: string | null;
    name: string;
}
export interface SearchResponse {
    query: string;
    results: SearchResultItem[];
}
export interface SearchResultItem {
    batch_id: string;
    batch_mode?: string | null;
    batch_name?: string | null;
    description?: string | null;
    image_id: number;
    image_name?: string | null;
    prompt?: string | null;
    score: number;
    tags?: string[];
    thumbnail_path?: string | null;
    variation_label?: string | null;
    volume_path?: string | null;
}
export interface SettingsOut {
    default_input_fidelity: string;
    default_output_format: string;
    default_quality: string;
    default_resolution: string;
    image_model: string;
    model_name: string;
    vision_volume: string;
}
export interface SettingsUpdate {
    default_input_fidelity?: string | null;
    default_output_format?: string | null;
    default_quality?: string | null;
    default_resolution?: string | null;
    image_model?: string | null;
    model_name?: string | null;
    vision_volume?: string | null;
}
export interface StyleGuidelineCreate {
    body?: string;
    is_default?: boolean;
    name: string;
}
export interface StyleGuidelineOut {
    body: string;
    created_at?: string | null;
    id: number;
    is_default: boolean;
    name: string;
    updated_at?: string | null;
}
export interface StyleGuidelineUpdate {
    body?: string | null;
    is_default?: boolean | null;
    name?: string | null;
}
export interface User {
    active?: boolean | null;
    display_name?: string | null;
    emails?: ComplexValue[] | null;
    entitlements?: ComplexValue[] | null;
    external_id?: string | null;
    groups?: ComplexValue[] | null;
    id?: string | null;
    name?: Name | null;
    roles?: ComplexValue[] | null;
    schemas?: UserSchema[] | null;
    user_name?: string | null;
}
export const UserSchema = {
    "urn:ietf:params:scim:schemas:core:2.0:User": "urn:ietf:params:scim:schemas:core:2.0:User",
    "urn:ietf:params:scim:schemas:extension:workspace:2.0:User": "urn:ietf:params:scim:schemas:extension:workspace:2.0:User"
} as const;
export type UserSchema = typeof UserSchema[keyof typeof UserSchema];
export interface ValidationError {
    ctx?: Record<string, unknown>;
    input?: unknown;
    loc: (string | number)[];
    msg: string;
    type: string;
}
export interface VariationItem {
    label: string;
    prompt: string;
}
export interface VersionOut {
    version: string;
}
export interface VolumeOut {
    full_name: string;
    name: string;
    volume_type?: string | null;
}
export const getAppConfig = async (options?: RequestInit): Promise<{
    data: AppConfigOut;
}> =>{
    const res = await fetch("/api/app-config", {
        ...options,
        method: "GET"
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export const getAppConfigKey = ()=>{
    return [
        "/api/app-config"
    ] as const;
};
export function useGetAppConfig<TData = {
    data: AppConfigOut;
}>(options?: {
    query?: Omit<UseQueryOptions<{
        data: AppConfigOut;
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useQuery({
        queryKey: getAppConfigKey(),
        queryFn: ()=>getAppConfig(),
        ...options?.query
    });
}
export function useGetAppConfigSuspense<TData = {
    data: AppConfigOut;
}>(options?: {
    query?: Omit<UseSuspenseQueryOptions<{
        data: AppConfigOut;
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useSuspenseQuery({
        queryKey: getAppConfigKey(),
        queryFn: ()=>getAppConfig(),
        ...options?.query
    });
}
export interface GetSourceImageParams {
    path: string;
    "X-Forwarded-Host"?: string | null;
    "X-Forwarded-Preferred-Username"?: string | null;
    "X-Forwarded-User"?: string | null;
    "X-Forwarded-Email"?: string | null;
    "X-Request-Id"?: string | null;
    "X-Forwarded-Access-Token"?: string | null;
}
export const getSourceImage = async (params: GetSourceImageParams, options?: RequestInit): Promise<{
    data: unknown;
}> =>{
    const searchParams = new URLSearchParams();
    if (params.path != null) searchParams.set("path", String(params.path));
    const queryString = searchParams.toString();
    const url = queryString ? `/api/batch-images/source?${queryString}` : "/api/batch-images/source";
    const res = await fetch(url, {
        ...options,
        method: "GET",
        headers: {
            ...(params?.["X-Forwarded-Host"] != null && {
                "X-Forwarded-Host": params["X-Forwarded-Host"]
            }),
            ...(params?.["X-Forwarded-Preferred-Username"] != null && {
                "X-Forwarded-Preferred-Username": params["X-Forwarded-Preferred-Username"]
            }),
            ...(params?.["X-Forwarded-User"] != null && {
                "X-Forwarded-User": params["X-Forwarded-User"]
            }),
            ...(params?.["X-Forwarded-Email"] != null && {
                "X-Forwarded-Email": params["X-Forwarded-Email"]
            }),
            ...(params?.["X-Request-Id"] != null && {
                "X-Request-Id": params["X-Request-Id"]
            }),
            ...(params?.["X-Forwarded-Access-Token"] != null && {
                "X-Forwarded-Access-Token": params["X-Forwarded-Access-Token"]
            }),
            ...options?.headers
        }
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export const getSourceImageKey = (params?: GetSourceImageParams)=>{
    return [
        "/api/batch-images/source",
        params
    ] as const;
};
export function useGetSourceImage<TData = {
    data: unknown;
}>(options: {
    params: GetSourceImageParams;
    query?: Omit<UseQueryOptions<{
        data: unknown;
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useQuery({
        queryKey: getSourceImageKey(options.params),
        queryFn: ()=>getSourceImage(options.params),
        ...options?.query
    });
}
export function useGetSourceImageSuspense<TData = {
    data: unknown;
}>(options: {
    params: GetSourceImageParams;
    query?: Omit<UseSuspenseQueryOptions<{
        data: unknown;
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useSuspenseQuery({
        queryKey: getSourceImageKey(options.params),
        queryFn: ()=>getSourceImage(options.params),
        ...options?.query
    });
}
export interface GetGeneratedImageParams {
    batch_id: string;
    filename: string;
    "X-Forwarded-Host"?: string | null;
    "X-Forwarded-Preferred-Username"?: string | null;
    "X-Forwarded-User"?: string | null;
    "X-Forwarded-Email"?: string | null;
    "X-Request-Id"?: string | null;
    "X-Forwarded-Access-Token"?: string | null;
}
export const getGeneratedImage = async (params: GetGeneratedImageParams, options?: RequestInit): Promise<{
    data: unknown;
}> =>{
    const res = await fetch(`/api/batch-images/${params.batch_id}/${params.filename}`, {
        ...options,
        method: "GET",
        headers: {
            ...(params?.["X-Forwarded-Host"] != null && {
                "X-Forwarded-Host": params["X-Forwarded-Host"]
            }),
            ...(params?.["X-Forwarded-Preferred-Username"] != null && {
                "X-Forwarded-Preferred-Username": params["X-Forwarded-Preferred-Username"]
            }),
            ...(params?.["X-Forwarded-User"] != null && {
                "X-Forwarded-User": params["X-Forwarded-User"]
            }),
            ...(params?.["X-Forwarded-Email"] != null && {
                "X-Forwarded-Email": params["X-Forwarded-Email"]
            }),
            ...(params?.["X-Request-Id"] != null && {
                "X-Request-Id": params["X-Request-Id"]
            }),
            ...(params?.["X-Forwarded-Access-Token"] != null && {
                "X-Forwarded-Access-Token": params["X-Forwarded-Access-Token"]
            }),
            ...options?.headers
        }
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export const getGeneratedImageKey = (params?: GetGeneratedImageParams)=>{
    return [
        "/api/batch-images/{batch_id}/{filename}",
        params
    ] as const;
};
export function useGetGeneratedImage<TData = {
    data: unknown;
}>(options: {
    params: GetGeneratedImageParams;
    query?: Omit<UseQueryOptions<{
        data: unknown;
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useQuery({
        queryKey: getGeneratedImageKey(options.params),
        queryFn: ()=>getGeneratedImage(options.params),
        ...options?.query
    });
}
export function useGetGeneratedImageSuspense<TData = {
    data: unknown;
}>(options: {
    params: GetGeneratedImageParams;
    query?: Omit<UseSuspenseQueryOptions<{
        data: unknown;
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useSuspenseQuery({
        queryKey: getGeneratedImageKey(options.params),
        queryFn: ()=>getGeneratedImage(options.params),
        ...options?.query
    });
}
export const listBatches = async (options?: RequestInit): Promise<{
    data: BatchRunOut[];
}> =>{
    const res = await fetch("/api/batches", {
        ...options,
        method: "GET"
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export const listBatchesKey = ()=>{
    return [
        "/api/batches"
    ] as const;
};
export function useListBatches<TData = {
    data: BatchRunOut[];
}>(options?: {
    query?: Omit<UseQueryOptions<{
        data: BatchRunOut[];
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useQuery({
        queryKey: listBatchesKey(),
        queryFn: ()=>listBatches(),
        ...options?.query
    });
}
export function useListBatchesSuspense<TData = {
    data: BatchRunOut[];
}>(options?: {
    query?: Omit<UseSuspenseQueryOptions<{
        data: BatchRunOut[];
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useSuspenseQuery({
        queryKey: listBatchesKey(),
        queryFn: ()=>listBatches(),
        ...options?.query
    });
}
export interface CreateBatchParams {
    "X-Forwarded-Host"?: string | null;
    "X-Forwarded-Preferred-Username"?: string | null;
    "X-Forwarded-User"?: string | null;
    "X-Forwarded-Email"?: string | null;
    "X-Request-Id"?: string | null;
    "X-Forwarded-Access-Token"?: string | null;
}
export const createBatch = async (data: BatchCreate, params?: CreateBatchParams, options?: RequestInit): Promise<{
    data: BatchRunOut;
}> =>{
    const res = await fetch("/api/batches", {
        ...options,
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            ...(params?.["X-Forwarded-Host"] != null && {
                "X-Forwarded-Host": params["X-Forwarded-Host"]
            }),
            ...(params?.["X-Forwarded-Preferred-Username"] != null && {
                "X-Forwarded-Preferred-Username": params["X-Forwarded-Preferred-Username"]
            }),
            ...(params?.["X-Forwarded-User"] != null && {
                "X-Forwarded-User": params["X-Forwarded-User"]
            }),
            ...(params?.["X-Forwarded-Email"] != null && {
                "X-Forwarded-Email": params["X-Forwarded-Email"]
            }),
            ...(params?.["X-Request-Id"] != null && {
                "X-Request-Id": params["X-Request-Id"]
            }),
            ...(params?.["X-Forwarded-Access-Token"] != null && {
                "X-Forwarded-Access-Token": params["X-Forwarded-Access-Token"]
            }),
            ...options?.headers
        },
        body: JSON.stringify(data)
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export function useCreateBatch(options?: {
    mutation?: UseMutationOptions<{
        data: BatchRunOut;
    }, ApiError, {
        params: CreateBatchParams;
        data: BatchCreate;
    }>;
}) {
    return useMutation({
        mutationFn: (vars)=>createBatch(vars.data, vars.params),
        ...options?.mutation
    });
}
export interface GetBatchDetailParams {
    batch_id: string;
}
export const getBatchDetail = async (params: GetBatchDetailParams, options?: RequestInit): Promise<{
    data: BatchDetailOut;
}> =>{
    const res = await fetch(`/api/batches/${params.batch_id}`, {
        ...options,
        method: "GET"
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export const getBatchDetailKey = (params?: GetBatchDetailParams)=>{
    return [
        "/api/batches/{batch_id}",
        params
    ] as const;
};
export function useGetBatchDetail<TData = {
    data: BatchDetailOut;
}>(options: {
    params: GetBatchDetailParams;
    query?: Omit<UseQueryOptions<{
        data: BatchDetailOut;
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useQuery({
        queryKey: getBatchDetailKey(options.params),
        queryFn: ()=>getBatchDetail(options.params),
        ...options?.query
    });
}
export function useGetBatchDetailSuspense<TData = {
    data: BatchDetailOut;
}>(options: {
    params: GetBatchDetailParams;
    query?: Omit<UseSuspenseQueryOptions<{
        data: BatchDetailOut;
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useSuspenseQuery({
        queryKey: getBatchDetailKey(options.params),
        queryFn: ()=>getBatchDetail(options.params),
        ...options?.query
    });
}
export interface DeleteBatchParams {
    batch_id: string;
}
export const deleteBatch = async (params: DeleteBatchParams, options?: RequestInit): Promise<{
    data: unknown;
}> =>{
    const res = await fetch(`/api/batches/${params.batch_id}`, {
        ...options,
        method: "DELETE"
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export function useDeleteBatch(options?: {
    mutation?: UseMutationOptions<{
        data: unknown;
    }, ApiError, {
        params: DeleteBatchParams;
    }>;
}) {
    return useMutation({
        mutationFn: (vars)=>deleteBatch(vars.params),
        ...options?.mutation
    });
}
export interface RegenerateImageParams {
    batch_id: string;
    image_id: number;
}
export const regenerateImage = async (params: RegenerateImageParams, data: RegenerateRequest, options?: RequestInit): Promise<{
    data: RegenerateResponse;
}> =>{
    const res = await fetch(`/api/batches/${params.batch_id}/images/${params.image_id}/regenerate`, {
        ...options,
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            ...options?.headers
        },
        body: JSON.stringify(data)
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export function useRegenerateImage(options?: {
    mutation?: UseMutationOptions<{
        data: RegenerateResponse;
    }, ApiError, {
        params: RegenerateImageParams;
        data: RegenerateRequest;
    }>;
}) {
    return useMutation({
        mutationFn: (vars)=>regenerateImage(vars.params, vars.data),
        ...options?.mutation
    });
}
export interface ListImageVersionsParams {
    batch_id: string;
    image_id: number;
}
export const listImageVersions = async (params: ListImageVersionsParams, options?: RequestInit): Promise<{
    data: ImageVersionOut[];
}> =>{
    const res = await fetch(`/api/batches/${params.batch_id}/images/${params.image_id}/versions`, {
        ...options,
        method: "GET"
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export const listImageVersionsKey = (params?: ListImageVersionsParams)=>{
    return [
        "/api/batches/{batch_id}/images/{image_id}/versions",
        params
    ] as const;
};
export function useListImageVersions<TData = {
    data: ImageVersionOut[];
}>(options: {
    params: ListImageVersionsParams;
    query?: Omit<UseQueryOptions<{
        data: ImageVersionOut[];
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useQuery({
        queryKey: listImageVersionsKey(options.params),
        queryFn: ()=>listImageVersions(options.params),
        ...options?.query
    });
}
export function useListImageVersionsSuspense<TData = {
    data: ImageVersionOut[];
}>(options: {
    params: ListImageVersionsParams;
    query?: Omit<UseSuspenseQueryOptions<{
        data: ImageVersionOut[];
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useSuspenseQuery({
        queryKey: listImageVersionsKey(options.params),
        queryFn: ()=>listImageVersions(options.params),
        ...options?.query
    });
}
export interface GetBatchStatusParams {
    batch_id: string;
}
export const getBatchStatus = async (params: GetBatchStatusParams, options?: RequestInit): Promise<{
    data: BatchRunOut;
}> =>{
    const res = await fetch(`/api/batches/${params.batch_id}/status`, {
        ...options,
        method: "GET"
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export const getBatchStatusKey = (params?: GetBatchStatusParams)=>{
    return [
        "/api/batches/{batch_id}/status",
        params
    ] as const;
};
export function useGetBatchStatus<TData = {
    data: BatchRunOut;
}>(options: {
    params: GetBatchStatusParams;
    query?: Omit<UseQueryOptions<{
        data: BatchRunOut;
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useQuery({
        queryKey: getBatchStatusKey(options.params),
        queryFn: ()=>getBatchStatus(options.params),
        ...options?.query
    });
}
export function useGetBatchStatusSuspense<TData = {
    data: BatchRunOut;
}>(options: {
    params: GetBatchStatusParams;
    query?: Omit<UseSuspenseQueryOptions<{
        data: BatchRunOut;
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useSuspenseQuery({
        queryKey: getBatchStatusKey(options.params),
        queryFn: ()=>getBatchStatus(options.params),
        ...options?.query
    });
}
export interface CurrentUserParams {
    "X-Forwarded-Host"?: string | null;
    "X-Forwarded-Preferred-Username"?: string | null;
    "X-Forwarded-User"?: string | null;
    "X-Forwarded-Email"?: string | null;
    "X-Request-Id"?: string | null;
    "X-Forwarded-Access-Token"?: string | null;
}
export const currentUser = async (params?: CurrentUserParams, options?: RequestInit): Promise<{
    data: User;
}> =>{
    const res = await fetch("/api/current-user", {
        ...options,
        method: "GET",
        headers: {
            ...(params?.["X-Forwarded-Host"] != null && {
                "X-Forwarded-Host": params["X-Forwarded-Host"]
            }),
            ...(params?.["X-Forwarded-Preferred-Username"] != null && {
                "X-Forwarded-Preferred-Username": params["X-Forwarded-Preferred-Username"]
            }),
            ...(params?.["X-Forwarded-User"] != null && {
                "X-Forwarded-User": params["X-Forwarded-User"]
            }),
            ...(params?.["X-Forwarded-Email"] != null && {
                "X-Forwarded-Email": params["X-Forwarded-Email"]
            }),
            ...(params?.["X-Request-Id"] != null && {
                "X-Request-Id": params["X-Request-Id"]
            }),
            ...(params?.["X-Forwarded-Access-Token"] != null && {
                "X-Forwarded-Access-Token": params["X-Forwarded-Access-Token"]
            }),
            ...options?.headers
        }
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export const currentUserKey = (params?: CurrentUserParams)=>{
    return [
        "/api/current-user",
        params
    ] as const;
};
export function useCurrentUser<TData = {
    data: User;
}>(options?: {
    params?: CurrentUserParams;
    query?: Omit<UseQueryOptions<{
        data: User;
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useQuery({
        queryKey: currentUserKey(options?.params),
        queryFn: ()=>currentUser(options?.params),
        ...options?.query
    });
}
export function useCurrentUserSuspense<TData = {
    data: User;
}>(options?: {
    params?: CurrentUserParams;
    query?: Omit<UseSuspenseQueryOptions<{
        data: User;
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useSuspenseQuery({
        queryKey: currentUserKey(options?.params),
        queryFn: ()=>currentUser(options?.params),
        ...options?.query
    });
}
export const editImages = async (data: Body_editImages, options?: RequestInit): Promise<{
    data: unknown;
}> =>{
    const res = await fetch("/api/edit", {
        ...options,
        method: "POST",
        headers: {
            "Content-Type": "application/x-www-form-urlencoded",
            ...options?.headers
        },
        body: new URLSearchParams(data as Record<string, string>)
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export function useEditImages(options?: {
    mutation?: UseMutationOptions<{
        data: unknown;
    }, ApiError, Body_editImages>;
}) {
    return useMutation({
        mutationFn: (data)=>editImages(data),
        ...options?.mutation
    });
}
export const listFolders = async (options?: RequestInit): Promise<{
    data: FolderOut[];
}> =>{
    const res = await fetch("/api/folders", {
        ...options,
        method: "GET"
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export const listFoldersKey = ()=>{
    return [
        "/api/folders"
    ] as const;
};
export function useListFolders<TData = {
    data: FolderOut[];
}>(options?: {
    query?: Omit<UseQueryOptions<{
        data: FolderOut[];
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useQuery({
        queryKey: listFoldersKey(),
        queryFn: ()=>listFolders(),
        ...options?.query
    });
}
export function useListFoldersSuspense<TData = {
    data: FolderOut[];
}>(options?: {
    query?: Omit<UseSuspenseQueryOptions<{
        data: FolderOut[];
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useSuspenseQuery({
        queryKey: listFoldersKey(),
        queryFn: ()=>listFolders(),
        ...options?.query
    });
}
export const createFolder = async (data: FolderCreate, options?: RequestInit): Promise<{
    data: FolderOut;
}> =>{
    const res = await fetch("/api/folders", {
        ...options,
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            ...options?.headers
        },
        body: JSON.stringify(data)
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export function useCreateFolder(options?: {
    mutation?: UseMutationOptions<{
        data: FolderOut;
    }, ApiError, FolderCreate>;
}) {
    return useMutation({
        mutationFn: (data)=>createFolder(data),
        ...options?.mutation
    });
}
export interface DeleteFolderParams {
    name: string;
    "X-Forwarded-Host"?: string | null;
    "X-Forwarded-Preferred-Username"?: string | null;
    "X-Forwarded-User"?: string | null;
    "X-Forwarded-Email"?: string | null;
    "X-Request-Id"?: string | null;
    "X-Forwarded-Access-Token"?: string | null;
}
export const deleteFolder = async (params: DeleteFolderParams, options?: RequestInit): Promise<{
    data: unknown;
}> =>{
    const res = await fetch(`/api/folders/${params.name}`, {
        ...options,
        method: "DELETE",
        headers: {
            ...(params?.["X-Forwarded-Host"] != null && {
                "X-Forwarded-Host": params["X-Forwarded-Host"]
            }),
            ...(params?.["X-Forwarded-Preferred-Username"] != null && {
                "X-Forwarded-Preferred-Username": params["X-Forwarded-Preferred-Username"]
            }),
            ...(params?.["X-Forwarded-User"] != null && {
                "X-Forwarded-User": params["X-Forwarded-User"]
            }),
            ...(params?.["X-Forwarded-Email"] != null && {
                "X-Forwarded-Email": params["X-Forwarded-Email"]
            }),
            ...(params?.["X-Request-Id"] != null && {
                "X-Request-Id": params["X-Request-Id"]
            }),
            ...(params?.["X-Forwarded-Access-Token"] != null && {
                "X-Forwarded-Access-Token": params["X-Forwarded-Access-Token"]
            }),
            ...options?.headers
        }
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export function useDeleteFolder(options?: {
    mutation?: UseMutationOptions<{
        data: unknown;
    }, ApiError, {
        params: DeleteFolderParams;
    }>;
}) {
    return useMutation({
        mutationFn: (vars)=>deleteFolder(vars.params),
        ...options?.mutation
    });
}
export interface ListGalleryImagesParams {
    folder?: string | null;
    batch_id?: string | null;
    mode?: string | null;
    page?: number;
    limit?: number;
}
export const listGalleryImages = async (params?: ListGalleryImagesParams, options?: RequestInit): Promise<{
    data: GeneratedImageOut[];
}> =>{
    const searchParams = new URLSearchParams();
    if (params?.folder != null) searchParams.set("folder", String(params?.folder));
    if (params?.batch_id != null) searchParams.set("batch_id", String(params?.batch_id));
    if (params?.mode != null) searchParams.set("mode", String(params?.mode));
    if (params?.page != null) searchParams.set("page", String(params?.page));
    if (params?.limit != null) searchParams.set("limit", String(params?.limit));
    const queryString = searchParams.toString();
    const url = queryString ? `/api/gallery?${queryString}` : "/api/gallery";
    const res = await fetch(url, {
        ...options,
        method: "GET"
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export const listGalleryImagesKey = (params?: ListGalleryImagesParams)=>{
    return [
        "/api/gallery",
        params
    ] as const;
};
export function useListGalleryImages<TData = {
    data: GeneratedImageOut[];
}>(options?: {
    params?: ListGalleryImagesParams;
    query?: Omit<UseQueryOptions<{
        data: GeneratedImageOut[];
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useQuery({
        queryKey: listGalleryImagesKey(options?.params),
        queryFn: ()=>listGalleryImages(options?.params),
        ...options?.query
    });
}
export function useListGalleryImagesSuspense<TData = {
    data: GeneratedImageOut[];
}>(options?: {
    params?: ListGalleryImagesParams;
    query?: Omit<UseSuspenseQueryOptions<{
        data: GeneratedImageOut[];
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useSuspenseQuery({
        queryKey: listGalleryImagesKey(options?.params),
        queryFn: ()=>listGalleryImages(options?.params),
        ...options?.query
    });
}
export const analyzeGalleryImages = async (data: Body_analyzeGalleryImages, options?: RequestInit): Promise<{
    data: unknown;
}> =>{
    const res = await fetch("/api/gallery/analyze", {
        ...options,
        method: "POST",
        headers: {
            "Content-Type": "application/x-www-form-urlencoded",
            ...options?.headers
        },
        body: new URLSearchParams(data as Record<string, string>)
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export function useAnalyzeGalleryImages(options?: {
    mutation?: UseMutationOptions<{
        data: unknown;
    }, ApiError, Body_analyzeGalleryImages>;
}) {
    return useMutation({
        mutationFn: (data)=>analyzeGalleryImages(data),
        ...options?.mutation
    });
}
export interface DeleteGalleryImageParams {
    batch_id: string;
    image_id: number;
    "X-Forwarded-Host"?: string | null;
    "X-Forwarded-Preferred-Username"?: string | null;
    "X-Forwarded-User"?: string | null;
    "X-Forwarded-Email"?: string | null;
    "X-Request-Id"?: string | null;
    "X-Forwarded-Access-Token"?: string | null;
}
export const deleteGalleryImage = async (params: DeleteGalleryImageParams, options?: RequestInit): Promise<{
    data: unknown;
}> =>{
    const res = await fetch(`/api/gallery/${params.batch_id}/${params.image_id}`, {
        ...options,
        method: "DELETE",
        headers: {
            ...(params?.["X-Forwarded-Host"] != null && {
                "X-Forwarded-Host": params["X-Forwarded-Host"]
            }),
            ...(params?.["X-Forwarded-Preferred-Username"] != null && {
                "X-Forwarded-Preferred-Username": params["X-Forwarded-Preferred-Username"]
            }),
            ...(params?.["X-Forwarded-User"] != null && {
                "X-Forwarded-User": params["X-Forwarded-User"]
            }),
            ...(params?.["X-Forwarded-Email"] != null && {
                "X-Forwarded-Email": params["X-Forwarded-Email"]
            }),
            ...(params?.["X-Request-Id"] != null && {
                "X-Request-Id": params["X-Request-Id"]
            }),
            ...(params?.["X-Forwarded-Access-Token"] != null && {
                "X-Forwarded-Access-Token": params["X-Forwarded-Access-Token"]
            }),
            ...options?.headers
        }
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export function useDeleteGalleryImage(options?: {
    mutation?: UseMutationOptions<{
        data: unknown;
    }, ApiError, {
        params: DeleteGalleryImageParams;
    }>;
}) {
    return useMutation({
        mutationFn: (vars)=>deleteGalleryImage(vars.params),
        ...options?.mutation
    });
}
export interface AnalyzeSingleImageParams {
    batch_id: string;
    image_id: number;
}
export const analyzeSingleImage = async (params: AnalyzeSingleImageParams, options?: RequestInit): Promise<{
    data: unknown;
}> =>{
    const res = await fetch(`/api/gallery/${params.batch_id}/${params.image_id}/analyze`, {
        ...options,
        method: "POST"
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export function useAnalyzeSingleImage(options?: {
    mutation?: UseMutationOptions<{
        data: unknown;
    }, ApiError, {
        params: AnalyzeSingleImageParams;
    }>;
}) {
    return useMutation({
        mutationFn: (vars)=>analyzeSingleImage(vars.params),
        ...options?.mutation
    });
}
export interface GetGalleryImageFileParams {
    batch_id: string;
    image_id: number;
    "X-Forwarded-Host"?: string | null;
    "X-Forwarded-Preferred-Username"?: string | null;
    "X-Forwarded-User"?: string | null;
    "X-Forwarded-Email"?: string | null;
    "X-Request-Id"?: string | null;
    "X-Forwarded-Access-Token"?: string | null;
}
export const getGalleryImageFile = async (params: GetGalleryImageFileParams, options?: RequestInit): Promise<{
    data: unknown;
}> =>{
    const res = await fetch(`/api/gallery/${params.batch_id}/${params.image_id}/file`, {
        ...options,
        method: "GET",
        headers: {
            ...(params?.["X-Forwarded-Host"] != null && {
                "X-Forwarded-Host": params["X-Forwarded-Host"]
            }),
            ...(params?.["X-Forwarded-Preferred-Username"] != null && {
                "X-Forwarded-Preferred-Username": params["X-Forwarded-Preferred-Username"]
            }),
            ...(params?.["X-Forwarded-User"] != null && {
                "X-Forwarded-User": params["X-Forwarded-User"]
            }),
            ...(params?.["X-Forwarded-Email"] != null && {
                "X-Forwarded-Email": params["X-Forwarded-Email"]
            }),
            ...(params?.["X-Request-Id"] != null && {
                "X-Request-Id": params["X-Request-Id"]
            }),
            ...(params?.["X-Forwarded-Access-Token"] != null && {
                "X-Forwarded-Access-Token": params["X-Forwarded-Access-Token"]
            }),
            ...options?.headers
        }
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export const getGalleryImageFileKey = (params?: GetGalleryImageFileParams)=>{
    return [
        "/api/gallery/{batch_id}/{image_id}/file",
        params
    ] as const;
};
export function useGetGalleryImageFile<TData = {
    data: unknown;
}>(options: {
    params: GetGalleryImageFileParams;
    query?: Omit<UseQueryOptions<{
        data: unknown;
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useQuery({
        queryKey: getGalleryImageFileKey(options.params),
        queryFn: ()=>getGalleryImageFile(options.params),
        ...options?.query
    });
}
export function useGetGalleryImageFileSuspense<TData = {
    data: unknown;
}>(options: {
    params: GetGalleryImageFileParams;
    query?: Omit<UseSuspenseQueryOptions<{
        data: unknown;
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useSuspenseQuery({
        queryKey: getGalleryImageFileKey(options.params),
        queryFn: ()=>getGalleryImageFile(options.params),
        ...options?.query
    });
}
export interface GetGalleryThumbnailParams {
    batch_id: string;
    image_id: number;
    "X-Forwarded-Host"?: string | null;
    "X-Forwarded-Preferred-Username"?: string | null;
    "X-Forwarded-User"?: string | null;
    "X-Forwarded-Email"?: string | null;
    "X-Request-Id"?: string | null;
    "X-Forwarded-Access-Token"?: string | null;
}
export const getGalleryThumbnail = async (params: GetGalleryThumbnailParams, options?: RequestInit): Promise<{
    data: unknown;
}> =>{
    const res = await fetch(`/api/gallery/${params.batch_id}/${params.image_id}/thumbnail`, {
        ...options,
        method: "GET",
        headers: {
            ...(params?.["X-Forwarded-Host"] != null && {
                "X-Forwarded-Host": params["X-Forwarded-Host"]
            }),
            ...(params?.["X-Forwarded-Preferred-Username"] != null && {
                "X-Forwarded-Preferred-Username": params["X-Forwarded-Preferred-Username"]
            }),
            ...(params?.["X-Forwarded-User"] != null && {
                "X-Forwarded-User": params["X-Forwarded-User"]
            }),
            ...(params?.["X-Forwarded-Email"] != null && {
                "X-Forwarded-Email": params["X-Forwarded-Email"]
            }),
            ...(params?.["X-Request-Id"] != null && {
                "X-Request-Id": params["X-Request-Id"]
            }),
            ...(params?.["X-Forwarded-Access-Token"] != null && {
                "X-Forwarded-Access-Token": params["X-Forwarded-Access-Token"]
            }),
            ...options?.headers
        }
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export const getGalleryThumbnailKey = (params?: GetGalleryThumbnailParams)=>{
    return [
        "/api/gallery/{batch_id}/{image_id}/thumbnail",
        params
    ] as const;
};
export function useGetGalleryThumbnail<TData = {
    data: unknown;
}>(options: {
    params: GetGalleryThumbnailParams;
    query?: Omit<UseQueryOptions<{
        data: unknown;
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useQuery({
        queryKey: getGalleryThumbnailKey(options.params),
        queryFn: ()=>getGalleryThumbnail(options.params),
        ...options?.query
    });
}
export function useGetGalleryThumbnailSuspense<TData = {
    data: unknown;
}>(options: {
    params: GetGalleryThumbnailParams;
    query?: Omit<UseSuspenseQueryOptions<{
        data: unknown;
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useSuspenseQuery({
        queryKey: getGalleryThumbnailKey(options.params),
        queryFn: ()=>getGalleryThumbnail(options.params),
        ...options?.query
    });
}
export const generateImages = async (data: Body_generateImages, options?: RequestInit): Promise<{
    data: unknown;
}> =>{
    const res = await fetch("/api/generate", {
        ...options,
        method: "POST",
        headers: {
            "Content-Type": "application/x-www-form-urlencoded",
            ...options?.headers
        },
        body: new URLSearchParams(data as Record<string, string>)
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export function useGenerateImages(options?: {
    mutation?: UseMutationOptions<{
        data: unknown;
    }, ApiError, Body_generateImages>;
}) {
    return useMutation({
        mutationFn: (data)=>generateImages(data),
        ...options?.mutation
    });
}
export const importImages = async (data: Body_importImages, options?: RequestInit): Promise<{
    data: unknown;
}> =>{
    const res = await fetch("/api/import", {
        ...options,
        method: "POST",
        headers: {
            "Content-Type": "application/x-www-form-urlencoded",
            ...options?.headers
        },
        body: new URLSearchParams(data as Record<string, string>)
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export function useImportImages(options?: {
    mutation?: UseMutationOptions<{
        data: unknown;
    }, ApiError, Body_importImages>;
}) {
    return useMutation({
        mutationFn: (data)=>importImages(data),
        ...options?.mutation
    });
}
export const rewritePrompt = async (data: Body_rewritePrompt, options?: RequestInit): Promise<{
    data: unknown;
}> =>{
    const res = await fetch("/api/rewrite", {
        ...options,
        method: "POST",
        headers: {
            "Content-Type": "application/x-www-form-urlencoded",
            ...options?.headers
        },
        body: new URLSearchParams(data as Record<string, string>)
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export function useRewritePrompt(options?: {
    mutation?: UseMutationOptions<{
        data: unknown;
    }, ApiError, Body_rewritePrompt>;
}) {
    return useMutation({
        mutationFn: (data)=>rewritePrompt(data),
        ...options?.mutation
    });
}
export interface SearchImagesParams {
    q: string;
    mode?: string;
    limit?: number;
}
export const searchImages = async (params: SearchImagesParams, options?: RequestInit): Promise<{
    data: SearchResponse;
}> =>{
    const searchParams = new URLSearchParams();
    if (params.q != null) searchParams.set("q", String(params.q));
    if (params?.mode != null) searchParams.set("mode", String(params?.mode));
    if (params?.limit != null) searchParams.set("limit", String(params?.limit));
    const queryString = searchParams.toString();
    const url = queryString ? `/api/search?${queryString}` : "/api/search";
    const res = await fetch(url, {
        ...options,
        method: "GET"
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export const searchImagesKey = (params?: SearchImagesParams)=>{
    return [
        "/api/search",
        params
    ] as const;
};
export function useSearchImages<TData = {
    data: SearchResponse;
}>(options: {
    params: SearchImagesParams;
    query?: Omit<UseQueryOptions<{
        data: SearchResponse;
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useQuery({
        queryKey: searchImagesKey(options.params),
        queryFn: ()=>searchImages(options.params),
        ...options?.query
    });
}
export function useSearchImagesSuspense<TData = {
    data: SearchResponse;
}>(options: {
    params: SearchImagesParams;
    query?: Omit<UseSuspenseQueryOptions<{
        data: SearchResponse;
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useSuspenseQuery({
        queryKey: searchImagesKey(options.params),
        queryFn: ()=>searchImages(options.params),
        ...options?.query
    });
}
export interface SearchByImageParams {
    limit?: number;
}
export const searchByImage = async (data: FormData, params?: SearchByImageParams, options?: RequestInit): Promise<{
    data: SearchResponse;
}> =>{
    const searchParams = new URLSearchParams();
    if (params?.limit != null) searchParams.set("limit", String(params?.limit));
    const queryString = searchParams.toString();
    const url = queryString ? `/api/search/by-image?${queryString}` : "/api/search/by-image";
    const res = await fetch(url, {
        ...options,
        method: "POST",
        headers: {
            ...options?.headers
        },
        body: data
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export function useSearchByImage(options?: {
    mutation?: UseMutationOptions<{
        data: SearchResponse;
    }, ApiError, {
        params: SearchByImageParams;
        data: FormData;
    }>;
}) {
    return useMutation({
        mutationFn: (vars)=>searchByImage(vars.data, vars.params),
        ...options?.mutation
    });
}
export interface SearchSimilarParams {
    batch_id: string;
    image_id: number;
    limit?: number;
}
export const searchSimilar = async (params: SearchSimilarParams, options?: RequestInit): Promise<{
    data: SearchResponse;
}> =>{
    const searchParams = new URLSearchParams();
    if (params?.limit != null) searchParams.set("limit", String(params?.limit));
    const queryString = searchParams.toString();
    const url = queryString ? `/api/search/similar/${params.batch_id}/${params.image_id}?${queryString}` : `/api/search/similar/${params.batch_id}/${params.image_id}`;
    const res = await fetch(url, {
        ...options,
        method: "GET"
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export const searchSimilarKey = (params?: SearchSimilarParams)=>{
    return [
        "/api/search/similar/{batch_id}/{image_id}",
        params
    ] as const;
};
export function useSearchSimilar<TData = {
    data: SearchResponse;
}>(options: {
    params: SearchSimilarParams;
    query?: Omit<UseQueryOptions<{
        data: SearchResponse;
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useQuery({
        queryKey: searchSimilarKey(options.params),
        queryFn: ()=>searchSimilar(options.params),
        ...options?.query
    });
}
export function useSearchSimilarSuspense<TData = {
    data: SearchResponse;
}>(options: {
    params: SearchSimilarParams;
    query?: Omit<UseSuspenseQueryOptions<{
        data: SearchResponse;
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useSuspenseQuery({
        queryKey: searchSimilarKey(options.params),
        queryFn: ()=>searchSimilar(options.params),
        ...options?.query
    });
}
export const getSettings = async (options?: RequestInit): Promise<{
    data: SettingsOut;
}> =>{
    const res = await fetch("/api/settings", {
        ...options,
        method: "GET"
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export const getSettingsKey = ()=>{
    return [
        "/api/settings"
    ] as const;
};
export function useGetSettings<TData = {
    data: SettingsOut;
}>(options?: {
    query?: Omit<UseQueryOptions<{
        data: SettingsOut;
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useQuery({
        queryKey: getSettingsKey(),
        queryFn: ()=>getSettings(),
        ...options?.query
    });
}
export function useGetSettingsSuspense<TData = {
    data: SettingsOut;
}>(options?: {
    query?: Omit<UseSuspenseQueryOptions<{
        data: SettingsOut;
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useSuspenseQuery({
        queryKey: getSettingsKey(),
        queryFn: ()=>getSettings(),
        ...options?.query
    });
}
export const updateSettings = async (data: SettingsUpdate, options?: RequestInit): Promise<{
    data: SettingsOut;
}> =>{
    const res = await fetch("/api/settings", {
        ...options,
        method: "PUT",
        headers: {
            "Content-Type": "application/json",
            ...options?.headers
        },
        body: JSON.stringify(data)
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export function useUpdateSettings(options?: {
    mutation?: UseMutationOptions<{
        data: SettingsOut;
    }, ApiError, SettingsUpdate>;
}) {
    return useMutation({
        mutationFn: (data)=>updateSettings(data),
        ...options?.mutation
    });
}
export const listStyleGuidelines = async (options?: RequestInit): Promise<{
    data: StyleGuidelineOut[];
}> =>{
    const res = await fetch("/api/style-guidelines", {
        ...options,
        method: "GET"
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export const listStyleGuidelinesKey = ()=>{
    return [
        "/api/style-guidelines"
    ] as const;
};
export function useListStyleGuidelines<TData = {
    data: StyleGuidelineOut[];
}>(options?: {
    query?: Omit<UseQueryOptions<{
        data: StyleGuidelineOut[];
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useQuery({
        queryKey: listStyleGuidelinesKey(),
        queryFn: ()=>listStyleGuidelines(),
        ...options?.query
    });
}
export function useListStyleGuidelinesSuspense<TData = {
    data: StyleGuidelineOut[];
}>(options?: {
    query?: Omit<UseSuspenseQueryOptions<{
        data: StyleGuidelineOut[];
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useSuspenseQuery({
        queryKey: listStyleGuidelinesKey(),
        queryFn: ()=>listStyleGuidelines(),
        ...options?.query
    });
}
export const createStyleGuideline = async (data: StyleGuidelineCreate, options?: RequestInit): Promise<{
    data: StyleGuidelineOut;
}> =>{
    const res = await fetch("/api/style-guidelines", {
        ...options,
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            ...options?.headers
        },
        body: JSON.stringify(data)
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export function useCreateStyleGuideline(options?: {
    mutation?: UseMutationOptions<{
        data: StyleGuidelineOut;
    }, ApiError, StyleGuidelineCreate>;
}) {
    return useMutation({
        mutationFn: (data)=>createStyleGuideline(data),
        ...options?.mutation
    });
}
export interface UpdateStyleGuidelineParams {
    guideline_id: number;
}
export const updateStyleGuideline = async (params: UpdateStyleGuidelineParams, data: StyleGuidelineUpdate, options?: RequestInit): Promise<{
    data: StyleGuidelineOut;
}> =>{
    const res = await fetch(`/api/style-guidelines/${params.guideline_id}`, {
        ...options,
        method: "PATCH",
        headers: {
            "Content-Type": "application/json",
            ...options?.headers
        },
        body: JSON.stringify(data)
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export function useUpdateStyleGuideline(options?: {
    mutation?: UseMutationOptions<{
        data: StyleGuidelineOut;
    }, ApiError, {
        params: UpdateStyleGuidelineParams;
        data: StyleGuidelineUpdate;
    }>;
}) {
    return useMutation({
        mutationFn: (vars)=>updateStyleGuideline(vars.params, vars.data),
        ...options?.mutation
    });
}
export interface DeleteStyleGuidelineParams {
    guideline_id: number;
}
export const deleteStyleGuideline = async (params: DeleteStyleGuidelineParams, options?: RequestInit): Promise<{
    data: unknown;
}> =>{
    const res = await fetch(`/api/style-guidelines/${params.guideline_id}`, {
        ...options,
        method: "DELETE"
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export function useDeleteStyleGuideline(options?: {
    mutation?: UseMutationOptions<{
        data: unknown;
    }, ApiError, {
        params: DeleteStyleGuidelineParams;
    }>;
}) {
    return useMutation({
        mutationFn: (vars)=>deleteStyleGuideline(vars.params),
        ...options?.mutation
    });
}
export const version = async (options?: RequestInit): Promise<{
    data: VersionOut;
}> =>{
    const res = await fetch("/api/version", {
        ...options,
        method: "GET"
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export const versionKey = ()=>{
    return [
        "/api/version"
    ] as const;
};
export function useVersion<TData = {
    data: VersionOut;
}>(options?: {
    query?: Omit<UseQueryOptions<{
        data: VersionOut;
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useQuery({
        queryKey: versionKey(),
        queryFn: ()=>version(),
        ...options?.query
    });
}
export function useVersionSuspense<TData = {
    data: VersionOut;
}>(options?: {
    query?: Omit<UseSuspenseQueryOptions<{
        data: VersionOut;
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useSuspenseQuery({
        queryKey: versionKey(),
        queryFn: ()=>version(),
        ...options?.query
    });
}
export interface BrowseVolumeFilesParams {
    path: string;
    "X-Forwarded-Host"?: string | null;
    "X-Forwarded-Preferred-Username"?: string | null;
    "X-Forwarded-User"?: string | null;
    "X-Forwarded-Email"?: string | null;
    "X-Request-Id"?: string | null;
    "X-Forwarded-Access-Token"?: string | null;
}
export const browseVolumeFiles = async (params: BrowseVolumeFilesParams, options?: RequestInit): Promise<{
    data: FileEntryOut[];
}> =>{
    const searchParams = new URLSearchParams();
    if (params.path != null) searchParams.set("path", String(params.path));
    const queryString = searchParams.toString();
    const url = queryString ? `/api/volumes/browse?${queryString}` : "/api/volumes/browse";
    const res = await fetch(url, {
        ...options,
        method: "GET",
        headers: {
            ...(params?.["X-Forwarded-Host"] != null && {
                "X-Forwarded-Host": params["X-Forwarded-Host"]
            }),
            ...(params?.["X-Forwarded-Preferred-Username"] != null && {
                "X-Forwarded-Preferred-Username": params["X-Forwarded-Preferred-Username"]
            }),
            ...(params?.["X-Forwarded-User"] != null && {
                "X-Forwarded-User": params["X-Forwarded-User"]
            }),
            ...(params?.["X-Forwarded-Email"] != null && {
                "X-Forwarded-Email": params["X-Forwarded-Email"]
            }),
            ...(params?.["X-Request-Id"] != null && {
                "X-Request-Id": params["X-Request-Id"]
            }),
            ...(params?.["X-Forwarded-Access-Token"] != null && {
                "X-Forwarded-Access-Token": params["X-Forwarded-Access-Token"]
            }),
            ...options?.headers
        }
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export const browseVolumeFilesKey = (params?: BrowseVolumeFilesParams)=>{
    return [
        "/api/volumes/browse",
        params
    ] as const;
};
export function useBrowseVolumeFiles<TData = {
    data: FileEntryOut[];
}>(options: {
    params: BrowseVolumeFilesParams;
    query?: Omit<UseQueryOptions<{
        data: FileEntryOut[];
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useQuery({
        queryKey: browseVolumeFilesKey(options.params),
        queryFn: ()=>browseVolumeFiles(options.params),
        ...options?.query
    });
}
export function useBrowseVolumeFilesSuspense<TData = {
    data: FileEntryOut[];
}>(options: {
    params: BrowseVolumeFilesParams;
    query?: Omit<UseSuspenseQueryOptions<{
        data: FileEntryOut[];
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useSuspenseQuery({
        queryKey: browseVolumeFilesKey(options.params),
        queryFn: ()=>browseVolumeFiles(options.params),
        ...options?.query
    });
}
export const listCatalogs = async (options?: RequestInit): Promise<{
    data: CatalogOut[];
}> =>{
    const res = await fetch("/api/volumes/catalogs", {
        ...options,
        method: "GET"
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export const listCatalogsKey = ()=>{
    return [
        "/api/volumes/catalogs"
    ] as const;
};
export function useListCatalogs<TData = {
    data: CatalogOut[];
}>(options?: {
    query?: Omit<UseQueryOptions<{
        data: CatalogOut[];
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useQuery({
        queryKey: listCatalogsKey(),
        queryFn: ()=>listCatalogs(),
        ...options?.query
    });
}
export function useListCatalogsSuspense<TData = {
    data: CatalogOut[];
}>(options?: {
    query?: Omit<UseSuspenseQueryOptions<{
        data: CatalogOut[];
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useSuspenseQuery({
        queryKey: listCatalogsKey(),
        queryFn: ()=>listCatalogs(),
        ...options?.query
    });
}
export interface ListSchemasParams {
    catalog_name: string;
}
export const listSchemas = async (params: ListSchemasParams, options?: RequestInit): Promise<{
    data: SchemaOut[];
}> =>{
    const res = await fetch(`/api/volumes/catalogs/${params.catalog_name}/schemas`, {
        ...options,
        method: "GET"
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export const listSchemasKey = (params?: ListSchemasParams)=>{
    return [
        "/api/volumes/catalogs/{catalog_name}/schemas",
        params
    ] as const;
};
export function useListSchemas<TData = {
    data: SchemaOut[];
}>(options: {
    params: ListSchemasParams;
    query?: Omit<UseQueryOptions<{
        data: SchemaOut[];
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useQuery({
        queryKey: listSchemasKey(options.params),
        queryFn: ()=>listSchemas(options.params),
        ...options?.query
    });
}
export function useListSchemasSuspense<TData = {
    data: SchemaOut[];
}>(options: {
    params: ListSchemasParams;
    query?: Omit<UseSuspenseQueryOptions<{
        data: SchemaOut[];
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useSuspenseQuery({
        queryKey: listSchemasKey(options.params),
        queryFn: ()=>listSchemas(options.params),
        ...options?.query
    });
}
export interface ListVolumesParams {
    catalog_name: string;
    schema_name: string;
}
export const listVolumes = async (params: ListVolumesParams, options?: RequestInit): Promise<{
    data: VolumeOut[];
}> =>{
    const res = await fetch(`/api/volumes/catalogs/${params.catalog_name}/schemas/${params.schema_name}/volumes`, {
        ...options,
        method: "GET"
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export const listVolumesKey = (params?: ListVolumesParams)=>{
    return [
        "/api/volumes/catalogs/{catalog_name}/schemas/{schema_name}/volumes",
        params
    ] as const;
};
export function useListVolumes<TData = {
    data: VolumeOut[];
}>(options: {
    params: ListVolumesParams;
    query?: Omit<UseQueryOptions<{
        data: VolumeOut[];
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useQuery({
        queryKey: listVolumesKey(options.params),
        queryFn: ()=>listVolumes(options.params),
        ...options?.query
    });
}
export function useListVolumesSuspense<TData = {
    data: VolumeOut[];
}>(options: {
    params: ListVolumesParams;
    query?: Omit<UseSuspenseQueryOptions<{
        data: VolumeOut[];
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useSuspenseQuery({
        queryKey: listVolumesKey(options.params),
        queryFn: ()=>listVolumes(options.params),
        ...options?.query
    });
}
