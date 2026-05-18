import { createFileRoute, useNavigate } from "@tanstack/react-router";
import Navbar from "@/components/apx/navbar";
import { BatchDetailContent } from "@/components/batch-detail";

export const Route = createFileRoute("/batch/$batchId")({
  component: () => {
    const { batchId } = Route.useParams();
    const navigate = useNavigate();

    // Redirect to gallery with batch context on next render
    // For now, render the batch detail with the gallery-like layout
    return (
      <div className="min-h-screen bg-background flex flex-col">
        <Navbar />
        <main className="flex-1 p-6 max-w-6xl mx-auto">
          <BatchDetailContent batchId={batchId} onDeleted={() => navigate({ to: "/" })} />
        </main>
      </div>
    );
  },
});
