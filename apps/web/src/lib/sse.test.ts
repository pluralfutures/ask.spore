import { describe, expect, it } from "vitest";

import { SseParser } from "./sse";

const frame = (event: string, data: unknown) =>
  `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;

describe("SseParser", () => {
  it("parses frames split at arbitrary points", () => {
    const body =
      frame("token", { text: "Grew " }) +
      frame("token", { text: "[1]." }) +
      frame("citations", { citations: [] }) +
      frame("done", { message_id: "m", unsupported: false });
    const parser = new SseParser();
    const events = [];
    for (let i = 0; i < body.length; i += 7) events.push(...parser.feed(body.slice(i, i + 7)));
    expect(events.map((e) => e.event)).toEqual(["token", "token", "citations", "done"]);
    expect(events[1]).toEqual({ event: "token", data: { text: "[1]." } });
  });

  it("accepts CRLF line endings and ignores unknown events", () => {
    const parser = new SseParser();
    const events = parser.feed(
      'event: ping\r\ndata: {}\r\n\r\nevent: error\r\ndata: {"error_code":"llm_5xx"}\r\n\r\n',
    );
    expect(events).toEqual([{ event: "error", data: { error_code: "llm_5xx" } }]);
  });
});
