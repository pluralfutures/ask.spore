// Incremental parser for the Server-Sent Events stream of POST .../messages.
// Frames are "event: <name>\ndata: <json>\n\n"; chunks may split frames anywhere.
import type { ChatStreamEvent } from "../api/types";

const EVENT_NAMES = new Set(["token", "citations", "done", "error"]);

export class SseParser {
  private buffer = "";

  /** Feed decoded text; returns every event completed by it. */
  feed(chunk: string): ChatStreamEvent[] {
    this.buffer += chunk.replace(/\r\n?/g, "\n");
    const events: ChatStreamEvent[] = [];
    let end = this.buffer.indexOf("\n\n");
    while (end !== -1) {
      const event = parseFrame(this.buffer.slice(0, end));
      if (event) events.push(event);
      this.buffer = this.buffer.slice(end + 2);
      end = this.buffer.indexOf("\n\n");
    }
    return events;
  }
}

function parseFrame(frame: string): ChatStreamEvent | null {
  let name = "message";
  const data: string[] = [];
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) name = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
  }
  if (!EVENT_NAMES.has(name) || data.length === 0) return null;
  return { event: name, data: JSON.parse(data.join("\n")) } as ChatStreamEvent;
}

/** Read a fetch Response body as chat stream events. */
export async function* readEvents(response: Response): AsyncGenerator<ChatStreamEvent> {
  if (!response.body) return;
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  const parser = new SseParser();
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    yield* parser.feed(value);
  }
}
