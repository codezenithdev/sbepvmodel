import template from "./html/document.template.html?raw";

const cssPartials = import.meta.glob<string>("./css/*.css", {
  eager: true,
  import: "default",
  query: "?raw",
});
const markupPartials = import.meta.glob<string>("./html/[0-9]*.html", {
  eager: true,
  import: "default",
  query: "?raw",
});
const scriptPartials = import.meta.glob<string>("./js/*.js", {
  eager: true,
  import: "default",
  query: "?raw",
});

function normalizeNewlines(source: string): string {
  return source.replace(/\r\n?/g, "\n");
}

function joinPartials(
  label: string,
  partials: Record<string, string>,
): string {
  const paths = Object.keys(partials).sort();
  if (paths.length === 0) {
    throw new Error(`No ${label} dashboard partials matched`);
  }

  return paths
    .map((path) => normalizeNewlines(partials[path]).replace(/\n$/, ""))
    .join("\n");
}

function replaceSlot(document: string, slot: string, content: string): string {
  const occurrences = document.split(slot).length - 1;
  if (occurrences !== 1) {
    throw new Error(
      `Dashboard template must contain ${slot} exactly once; found ${occurrences}`,
    );
  }
  return document.replace(slot, content);
}

export function assembleDashboardHtml(): string {
  let assembled = normalizeNewlines(template);
  assembled = replaceSlot(
    assembled,
    "{{CSS}}",
    joinPartials("CSS", cssPartials),
  );
  assembled = replaceSlot(
    assembled,
    "{{MARKUP}}",
    joinPartials("markup", markupPartials),
  );
  assembled = replaceSlot(
    assembled,
    "{{JS}}",
    joinPartials("JavaScript", scriptPartials),
  );
  return assembled;
}

export const dashboardHtml = assembleDashboardHtml();
