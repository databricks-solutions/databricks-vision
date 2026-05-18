export type SSEEvent =
  | { type: "partial"; index: number; image_b64: string }
  | { type: "done"; index: number; image_b64: string }
  | { type: "complete"; count: number }
  | { type: "error"; index: number; error: string };

export type SSECallbacks = {
  onPartial?: (index: number, b64: string) => void;
  onDone?: (index: number, b64: string) => void;
  onComplete?: (count: number) => void;
  onError?: (index: number, error: string) => void;
};

/**
 * Stream SSE events from a POST endpoint that returns EventSourceResponse.
 * Returns a cleanup function that aborts the request.
 */
export function streamSSE(
  url: string,
  body: FormData,
  callbacks: SSECallbacks,
  onFinished?: () => void
): () => void {
  const controller = new AbortController();

  (async () => {
    try {
      const res = await fetch(url, {
        method: "POST",
        body,
        signal: controller.signal,
      });

      if (!res.ok || !res.body) {
        const text = await res.text();
        callbacks.onError?.(-1, text || `HTTP ${res.status}`);
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      const processLines = (lines: string[], eventType: string): string => {
        for (const line of lines) {
          if (line.startsWith("event: ")) {
            eventType = line.slice(7).trim();
          } else if (line.startsWith("data: ")) {
            const data = line.slice(6).trim();
            try {
              const parsed = JSON.parse(data);
              if (eventType === "partial") {
                callbacks.onPartial?.(parsed.index, parsed.image_b64);
              } else if (eventType === "done") {
                callbacks.onDone?.(parsed.index, parsed.image_b64);
              } else if (eventType === "complete") {
                callbacks.onComplete?.(parsed.count);
              } else if (eventType === "error") {
                callbacks.onError?.(parsed.index, parsed.error);
              }
            } catch {
              // ignore parse errors
            }
            eventType = "";
          }
        }
        return eventType;
      };

      let eventType = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";
        eventType = processLines(lines, eventType);
      }

      // Process any remaining data in the buffer after stream ends
      if (buffer.trim()) {
        const lines = buffer.split("\n");
        processLines(lines, eventType);
      }
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        callbacks.onError?.(-1, String(err));
      }
    } finally {
      onFinished?.();
    }
  })();

  return () => controller.abort();
}
