import type { ImageModelOut } from "@/lib/api";

// Mirrors image_gen.TRANSPARENT_FALLBACK_MODEL: serves transparent-BG requests for models
// that can't render transparency (e.g. gpt-image-2).
export const TRANSPARENT_FALLBACK_MODEL = "gpt-image-1.5";

// The user's image-model pick, remembered per browser. Written by the Generate page picker
// and by Settings → "Default image model".
export const IMAGE_MODEL_STORAGE_KEY = "generate-image-model";

// Used until the model list has loaded.
export const DEFAULT_QUALITIES = ["auto", "low", "medium", "high"];

export const QUALITY_LABELS: Record<string, string> = {
  auto: "Auto",
  low: "Low",
  medium: "Medium",
  high: "High",
  xhigh: "Extra high",
  max: "Max",
};

// The model that will actually serve a request — mirrors image_gen.resolve_image_model.
export function resolveImageModel(
  models: ImageModelOut[],
  model: ImageModelOut | undefined,
  transparent: boolean,
): ImageModelOut | undefined {
  if (transparent && model && !model.supports_transparent) {
    return models.find((m) => m.id === TRANSPARENT_FALLBACK_MODEL) ?? model;
  }
  return model;
}
