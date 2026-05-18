import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import Navbar from "@/components/apx/navbar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
} from "@/components/ui/tabs";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  useListStyleGuidelines,
  useCreateStyleGuideline,
  useUpdateStyleGuideline,
  listStyleGuidelinesKey,
  useGetSettings,
  useUpdateSettings,
  type StyleGuidelineOut,
  type SettingsOut,
  type SettingsUpdate,
} from "@/lib/api";
import { Save, Sparkles, Plus, Trash2, Pencil } from "lucide-react";
import { toast } from "sonner";

export const Route = createFileRoute("/settings")({
  component: SettingsPage,
});

function SettingsPage() {
  return (
    <div className="min-h-screen bg-background flex flex-col">
      <Navbar />
      <main className="flex-1 px-4 sm:px-6 py-6 max-w-4xl w-full mx-auto">
        <h1 className="text-2xl font-semibold mb-1">Settings</h1>
        <p className="text-sm text-muted-foreground mb-6">
          Manage style guidelines used by the analyzer and configure default generation models.
        </p>
        <Tabs defaultValue="guidelines" className="w-full">
          <TabsList>
            <TabsTrigger value="guidelines">Style Guidelines</TabsTrigger>
            <TabsTrigger value="models">Model Settings</TabsTrigger>
          </TabsList>
          <TabsContent value="guidelines" className="pt-4">
            <StyleGuidelinesTab />
          </TabsContent>
          <TabsContent value="models" className="pt-4">
            <ModelSettingsTab />
          </TabsContent>
        </Tabs>
      </main>
    </div>
  );
}

// ──────────────────────────────────────────────────────────
// Style Guidelines tab
// ──────────────────────────────────────────────────────────

function StyleGuidelinesTab() {
  const queryClient = useQueryClient();
  const { data, isLoading } = useListStyleGuidelines();
  const guidelines: StyleGuidelineOut[] = data?.data ?? [];

  const createMutation = useCreateStyleGuideline();
  const updateMutation = useUpdateStyleGuideline();

  const [editing, setEditing] = useState<StyleGuidelineOut | null>(null);
  const [creating, setCreating] = useState(false);
  const [deleting, setDeleting] = useState<StyleGuidelineOut | null>(null);

  function invalidate() {
    queryClient.invalidateQueries({ queryKey: listStyleGuidelinesKey() });
  }

  async function handleDelete(g: StyleGuidelineOut) {
    try {
      const res = await fetch(`/api/style-guidelines/${g.id}`, { method: "DELETE" });
      if (!res.ok) throw new Error(await res.text());
      toast.success(`Deleted "${g.name}"`);
      setDeleting(null);
      invalidate();
    } catch (e) {
      toast.error(`Delete failed: ${e}`);
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Saved guidelines appear in the Style guideline dropdown on the Generate form. Mark one as
          default to pre-select it for new generations.
        </p>
        <Button size="sm" onClick={() => setCreating(true)}>
          <Plus className="h-4 w-4 mr-1" />New
        </Button>
      </div>

      {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
      {!isLoading && guidelines.length === 0 && (
        <div className="border border-dashed rounded-lg p-8 text-center text-sm text-muted-foreground">
          No guidelines yet. Click <span className="font-medium text-foreground">New</span> to create one.
        </div>
      )}

      <div className="space-y-2">
        {guidelines.map((g) => (
          <div
            key={g.id}
            className="border rounded-md p-3 hover:border-foreground/30 transition-colors"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 mb-0.5">
                  <span className="font-medium text-sm truncate">{g.name}</span>
                  {g.is_default && (
                    <Badge variant="secondary" className="text-[10px] uppercase">Default</Badge>
                  )}
                </div>
                <p className="text-xs text-muted-foreground line-clamp-2 whitespace-pre-line">
                  {g.body || <span className="italic">No body</span>}
                </p>
              </div>
              <div className="flex gap-1 shrink-0">
                <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => setEditing(g)}>
                  <Pencil className="h-3.5 w-3.5" />
                </Button>
                <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => setDeleting(g)}>
                  <Trash2 className="h-3.5 w-3.5 text-red-600 dark:text-red-400" />
                </Button>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Create dialog */}
      <GuidelineDialog
        open={creating}
        onOpenChange={(o) => !o && setCreating(false)}
        title="New style guideline"
        initial={{ name: "", body: "", is_default: guidelines.length === 0 }}
        onSubmit={async (form) => {
          await createMutation.mutateAsync(form);
          toast.success(`Created "${form.name}"`);
          invalidate();
          setCreating(false);
        }}
        submitting={createMutation.isPending}
      />

      {/* Edit dialog */}
      <GuidelineDialog
        open={editing !== null}
        onOpenChange={(o) => !o && setEditing(null)}
        title="Edit style guideline"
        initial={
          editing
            ? { name: editing.name, body: editing.body, is_default: editing.is_default }
            : null
        }
        onSubmit={async (form) => {
          if (!editing) return;
          await updateMutation.mutateAsync({
            params: { guideline_id: editing.id },
            data: form,
          });
          toast.success(`Updated "${form.name}"`);
          invalidate();
          setEditing(null);
        }}
        submitting={updateMutation.isPending}
      />

      {/* Delete confirmation — matches the image-dialog delete pattern */}
      <Dialog open={deleting !== null} onOpenChange={(o) => !o && setDeleting(null)}>
        <DialogContent>
          <DialogTitle>Delete style guideline "{deleting?.name}"?</DialogTitle>
          <DialogDescription>This will not affect existing images. Cannot be undone.</DialogDescription>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleting(null)}>Cancel</Button>
            <Button
              variant="destructive"
              className="text-white"
              onClick={() => deleting && handleDelete(deleting)}
            >
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

interface GuidelineForm {
  name: string;
  body: string;
  is_default: boolean;
}

function GuidelineDialog({
  open,
  onOpenChange,
  title,
  initial,
  onSubmit,
  submitting,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  initial: GuidelineForm | null;
  onSubmit: (form: GuidelineForm) => Promise<void>;
  submitting: boolean;
}) {
  const [form, setForm] = useState<GuidelineForm>({ name: "", body: "", is_default: false });

  useEffect(() => {
    if (initial) setForm(initial);
  }, [initial]);

  async function handleSubmit() {
    if (!form.name.trim()) {
      toast.error("Name is required");
      return;
    }
    try {
      await onSubmit({ ...form, name: form.name.trim() });
    } catch (e) {
      toast.error(`Failed: ${e}`);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogTitle>{title}</DialogTitle>
        <div className="space-y-4 py-2">
          <div className="space-y-1.5">
            <Label htmlFor="g-name">Name</Label>
            <Input
              id="g-name"
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              placeholder="e.g. Databricks brand"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="g-body">Guideline</Label>
            <Textarea
              id="g-body"
              value={form.body}
              onChange={(e) => setForm((f) => ({ ...f, body: e.target.value }))}
              placeholder="Brand colours, on-brand props, do/don't elements. The analyzer will assess every generation against this."
              rows={8}
              className="resize-y text-xs font-mono"
            />
          </div>
          <label className="flex items-center gap-2 text-sm cursor-pointer select-none">
            <input
              type="checkbox"
              checked={form.is_default}
              onChange={(e) => setForm((f) => ({ ...f, is_default: e.target.checked }))}
              className="rounded border-input"
            />
            <span>Set as default (auto-applies on new generations)</span>
          </label>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>Cancel</Button>
          <Button onClick={handleSubmit} disabled={submitting}>
            <Save className="h-4 w-4 mr-2" />
            {submitting ? "Saving…" : "Save"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ──────────────────────────────────────────────────────────
// Model Settings tab (moved from the gear dialog on Generate)
// ──────────────────────────────────────────────────────────

function ModelSettingsTab() {
  const { data: settingsData } = useGetSettings();
  const updateSettingsMutation = useUpdateSettings();
  const [form, setForm] = useState<Partial<SettingsOut>>({});

  useEffect(() => {
    if (settingsData?.data) setForm(settingsData.data);
  }, [settingsData]);

  function handleSave() {
    updateSettingsMutation.mutate(form as SettingsUpdate, {
      onSuccess: () => toast.success("Settings saved"),
      onError: (err: { message?: string }) => toast.error(`Failed: ${err.message ?? "unknown"}`),
    });
  }

  if (!settingsData?.data) {
    return <p className="text-sm text-muted-foreground">Loading…</p>;
  }

  return (
    <div className="max-w-md space-y-4">
      <div className="space-y-1.5">
        <Label>Language Model</Label>
        <Select value={form.model_name ?? ""} onValueChange={(v) => setForm((f) => ({ ...f, model_name: v }))}>
          <SelectTrigger><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="databricks-gpt-5-5">GPT-5.5</SelectItem>
            <SelectItem value="databricks-gpt-5-2">GPT-5.2</SelectItem>
            <SelectItem value="databricks-claude-sonnet-4-5">Claude Sonnet 4.5</SelectItem>
            <SelectItem value="databricks-meta-llama-3-3-70b-instruct">Llama 3.3 70B</SelectItem>
          </SelectContent>
        </Select>
        <p className="text-xs text-muted-foreground">Used for analysis and prompt enhancement.</p>
      </div>
      <div className="space-y-1.5">
        <Label>Image Model</Label>
        <Select value={form.image_model ?? ""} onValueChange={(v) => setForm((f) => ({ ...f, image_model: v }))}>
          <SelectTrigger><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="gpt-image-2">gpt-image-2</SelectItem>
            <SelectItem value="gpt-image-1.5">gpt-image-1.5</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <div className="space-y-1.5">
        <Label>Generate Volume</Label>
        <input
          className="w-full px-3 py-2 text-sm border rounded-md bg-background font-mono"
          value={form.vision_volume ?? ""}
          onChange={(e) => setForm((f) => ({ ...f, vision_volume: e.target.value }))}
        />
        <p className="text-xs text-muted-foreground">UC Volume where generated images are saved.</p>
      </div>
      <div className="pt-2">
        <Button onClick={handleSave} disabled={updateSettingsMutation.isPending}>
          <Save className="h-4 w-4 mr-2" />
          {updateSettingsMutation.isPending ? "Saving…" : "Save"}
        </Button>
      </div>
      <p className="text-xs text-muted-foreground pt-2">
        <Sparkles className="h-3 w-3 inline mr-1" />
        Changes apply to new generations.
      </p>
    </div>
  );
}
