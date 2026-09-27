// SPDX-License-Identifier: AGPL-3.0-only
// SPDX-FileCopyrightText: 2026 Lany Atwood <lany@colorized.life>

// Civitai's app uses this parser with the civitai plugin:
// https://github.com/civitai/civitai/blob/329c89a23e1d5b4d6bade79f342fe6e31e15ab61/src/utils/metadata/index.ts
// Hash values feed the site's resource lookup independently of their labels:
// https://github.com/civitai/civitai/blob/329c89a23e1d5b4d6bade79f342fe6e31e15ab61/packages/civitai-db-schema/prisma/programmability/get_image_resources.sql
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { readCivitaiMetadata } from "@civitai/generation-metadata/civitai";

import { getFromPngBuffer } from "./fixtures/comfyui_png.mjs";

// pytest supplies files produced by the real node under the isolated host fixture.
const samples = JSON.parse(await readFile(process.argv[2], "utf8"));
const parserPackage = JSON.parse(
  await readFile(
    new URL(
      "../node_modules/@civitai/generation-metadata/package.json",
      import.meta.url,
    ),
    "utf8",
  ),
);
assert.equal(parserPackage.version, "0.3.0");
globalThis.fetch = () => {
  throw new Error("Metadata contract tests must run without network access.");
};

for (const sample of samples) {
  test(`Civitai 0.3.0: ${sample.name}`, async () => {
    const parsed = await readCivitaiMetadata(await readFile(sample.path));
    assert.equal(parsed.format, sample.format);
    assert.equal(parsed.generator, "automatic1111");
    for (const key of [
      "prompt",
      "negativePrompt",
      "steps",
      "seed",
      "width",
      "height",
      "Model",
      "Model hash",
      "hashes",
    ])
      assert.deepEqual(parsed.raw[key], sample.metadata[key] ?? undefined, key);
    assert.equal(parsed.raw.Version, "ComfyUI");

    const model = sample.metadata.Model;
    const hash = sample.metadata["Model hash"];
    assert.deepEqual(
      parsed.raw.resources,
      hash ? [{ type: "model", name: model, hash }] : [],
    );
    assert.deepEqual(
      parsed.civitai.generation.model,
      model ? { name: model, hash: hash ?? undefined } : undefined,
    );
  });

  if (sample.format === "png") {
    test(`ComfyUI PNG workflow recovery: ${sample.name}`, async () => {
      const bytes = await readFile(sample.path);
      const buffer = bytes.buffer.slice(
        bytes.byteOffset,
        bytes.byteOffset + bytes.byteLength,
      );
      const parsed = await getFromPngBuffer(buffer);
      assert.ok(parsed.parameters.includes("\nSteps: "));
      if (sample.workflow) {
        assert.deepEqual(JSON.parse(parsed.workflow), sample.workflow);
        assert.deepEqual(JSON.parse(parsed.prompt), sample.prompt);
      } else {
        assert.equal(parsed.workflow, undefined);
        assert.equal(parsed.prompt, undefined);
      }
    });
  }
}
