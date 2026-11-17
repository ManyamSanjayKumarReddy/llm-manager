import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { buildVllmCommand, imageRef, vllmProblems, type VllmParams } from "../src/lib/vllmCommand";

/** Split a shell command into words, the way a shell would (single and double quotes, line breaks). */
function words(command: string): string[] {
  const out: string[] = [];
  let current = "";
  let started = false;
  let quote: "'" | '"' | undefined;
  for (const ch of command.replaceAll("\\\n", " ")) {
    if (quote) {
      if (ch === quote) quote = undefined;
      else current += ch;
    } else if (ch === "'" || ch === '"') {
      quote = ch;
      started = true;
    } else if (/\s/.test(ch)) {
      if (started || current) out.push(current);
      current = "";
      started = false;
    } else {
      current += ch;
    }
  }
  if (started || current) out.push(current);
  return out;
}

interface Case {
  name: string;
  params: VllmParams;
  argv: string[];
}

// The agent builds the same `docker run` arguments from a structured description; this file is the
// shared proof that what the dashboard shows and what the agent runs do not drift apart.
const golden = JSON.parse(readFileSync(resolve(__dirname, "../../agent/tests/golden_commands.json"), "utf8")) as Case[];

describe("the command shown in the dashboard matches what the agent runs", () => {
  for (const c of golden) {
    it(c.name, () => {
      const command = buildVllmCommand(c.params);
      expect(command).not.toBeNull();
      const shown = words(command ?? "").slice(1); // without the leading "docker"
      // The dashboard's command shows an empty token slot for pasting; the agent leaves it out.
      const at = shown.indexOf("--env");
      if (at !== -1 && shown[at + 1] === "HUGGING_FACE_HUB_TOKEN=") shown.splice(at, 2);
      expect(shown).toEqual(c.argv);
    });
  }
});

describe("image references", () => {
  it("treats a bare tag as the official image and anything with a colon as given", () => {
    expect(imageRef("v0.10.1")).toBe("vllm/vllm-openai:v0.10.1");
    expect(imageRef("vllm-openai:v0.10.1-abortsleep")).toBe("vllm-openai:v0.10.1-abortsleep");
  });

  it("accepts the patched image in the command", () => {
    const base = golden[0]?.params as VllmParams;
    const patched = { ...base, imageTag: "vllm-openai:v0.10.1-abortsleep" };
    expect(vllmProblems(patched)).toEqual([]);
    expect(buildVllmCommand(patched)).toContain(" vllm-openai:v0.10.1-abortsleep");
    expect(vllmProblems({ ...base, imageTag: "evil image:1" })).toHaveLength(1);
  });
});
