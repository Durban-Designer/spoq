import { createHash } from "node:crypto";
import { lstatSync, readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
const buildFiles = [
  "index.html",
  "package.json",
  "package-lock.json",
  "tsconfig.json",
  "vite.config.ts",
  "scripts/source-hash.mjs",
];
export function sourceFingerprint(root) {
  function input(name, directory = false) {
    const components = name ? name.split("/") : [];
    let path = root;
    for (let index = 0; index <= components.length; index++) {
      if (index) path = join(path, components[index - 1]);
      const info = lstatSync(path);
      if (info.isSymbolicLink())
        throw new Error("UI build inputs cannot be symbolic links");
      const needsDirectory = index < components.length || directory;
      if (!(needsDirectory ? info.isDirectory() : info.isFile()))
        throw new Error(
          "Required production UI build input has an unsafe type",
        );
    }
    return path;
  }
  input("", true);
  const paths = buildFiles.map((name) => input(name));
  if (readdirSync(root).some((name) => name.startsWith(".env")))
    throw new Error("Managed UI builds do not load private .env files");
  function walk(dir, excluded = false) {
    for (const item of readdirSync(dir, { withFileTypes: true })) {
      const path = join(dir, item.name);
      if (item.isSymbolicLink())
        throw new Error("UI build inputs cannot be symbolic links");
      if (item.name.startsWith(".env"))
        throw new Error("Private environment files cannot be UI assets");
      if (item.isDirectory()) {
        walk(path, excluded || item.name === "__tests__");
      } else if (
        item.isFile() &&
        !excluded &&
        !/\.test\.[^.]+$/.test(item.name) &&
        !["test-setup.ts", "fixtures.test-support.ts"].includes(item.name)
      )
        paths.push(path);
      else if (!item.isFile())
        throw new Error("UI build inputs must be regular files or directories");
    }
  }
  walk(input("src", true));
  walk(input("public", true));
  const files = Object.fromEntries(
    paths
      .sort()
      .map((path) => [
        relative(root, path).replaceAll("\\", "/"),
        createHash("sha256").update(readFileSync(path)).digest("hex"),
      ]),
  );
  return {
    files,
    source_sha256: createHash("sha256")
      .update(JSON.stringify(files))
      .digest("hex"),
  };
}
export function licenseNotices(root) {
  const lock = JSON.parse(
    readFileSync(join(root, "package-lock.json"), "utf8"),
  );
  return Object.entries(lock.packages)
    .filter(([name, entry]) => name && !entry.dev)
    .map(([name, entry]) => {
      const dir = join(root, name);
      let license = "License: " + (entry.license ?? "See package metadata");
      for (const file of [
        "LICENSE",
        "LICENSE.md",
        "LICENSE.txt",
        "license",
        "license.md",
        "COPYING",
      ]) {
        try {
          license = readFileSync(join(dir, file), "utf8");
          break;
        } catch {}
      }
      return (
        name.replace(/^.*node_modules\//, "") +
        " @ " +
        entry.version +
        "\n" +
        license
      );
    })
    .join("\n\n" + "-".repeat(72) + "\n\n");
}
