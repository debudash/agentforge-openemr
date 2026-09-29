// Reads what the new dashboard shows, from the DOM attributes each card renders.
import type { Page } from "@playwright/test";

export interface PortCards {
  readonly header: { readonly name: string; readonly mrn: string; readonly dob: string; readonly age: string; readonly sex: string; readonly status: string };
  readonly cards: Readonly<Record<string, { readonly state: string; readonly text: string; readonly items: readonly string[] }>>;
  readonly vitals: { readonly date: string | null; readonly values: Readonly<Record<string, string>> };
}

export async function extractPort(page: Page): Promise<PortCards> {
  return page.evaluate(() => {
    const field = (f: string) => document.querySelector(`[data-field="${f}"]`)?.textContent.trim() ?? "";
    const cards: Record<string, { state: string; text: string; items: string[] }> = {};
    for (const el of document.querySelectorAll<HTMLElement>("[data-card]")) {
      const id = el.dataset.card ?? "";
      const body = el.querySelector(`[data-card-body="${id}"]`);
      cards[id] = {
        state: el.dataset.state ?? "",
        text: (body?.textContent ?? "").replace(/\s+/g, " ").trim(),
        items: [...(body?.querySelectorAll<HTMLElement>("[data-item]") ?? [])].map((i) => i.dataset.item ?? ""),
      };
    }
    const values: Record<string, string> = {};
    for (const row of document.querySelectorAll<HTMLElement>('[data-card="vitals"] [data-item]')) values[row.dataset.item ?? ""] = row.dataset.value ?? "";
    return {
      header: { name: field("name"), mrn: field("mrn"), dob: field("dob"), age: field("age"), sex: field("sex"), status: field("status") },
      cards,
      vitals: { date: document.querySelector<HTMLElement>("[data-vitals-date]")?.dataset.vitalsDate ?? null, values },
    };
  });
}
