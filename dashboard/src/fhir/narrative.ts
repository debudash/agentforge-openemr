// OpenEMR puts some titles only in Resource.text.div (XHTML), e.g. an allergy with no coded
// substance. The div is reduced to plain text with an inert parser (DOMParser documents run no
// scripts and load nothing) and then rendered as text like every other value (R3).
export function narrativeText(div: string | undefined | null): string {
  if (!div) return "";
  const doc = new DOMParser().parseFromString(div, "text/html");
  return doc.body.textContent.replace(/\s+/g, " ").trim();
}
