# interface/patient_file/summary/pnotes_fragment.php

**Role:** body of the Messages card, and the endpoint that marks a message "Completed".
**Size:** 137 lines. **Reached from:** `placeHtml("pnotes_fragment.php", 'pnotes_ps_expand')` (demographics.php L611) and the Completed button (L613-624).

## Purpose and lifecycle

Two modes. With `?docUpdateId=` it calls `disappearPnote($id, $pid)` and returns (L22-24).
Otherwise it checks `patients/notes` and the squad (L33-39), loads the newest N active notes for the
session patient (L49-58), strips the "(user to user)" routing prefix from each body and substitutes
the patient's name for `-patient-` (L78-79), and prints a table with a Completed button per row.

## Controls

- **CSRF:** checked (L16), before either mode.
- **Authorization:** the only fragment that checks both the ACL and the squad (L33-39), but only for
  display. The **write** at L22-24 runs before that check and needs no write permission.
  `disappearPnote()` does verify that the note belongs to the session patient (pnotes.inc.php L497-501).
- **Escaping:** `text()` on user, assignee, date and body; `generate_display_field` for the title;
  `pnoteConvertLinks(nl2br(text($body)))` turns document references into links after escaping.

## Database touches

Reads `pnotes`, `patient_data` (twice), `list_options`. Writes `pnotes.activity`,
`message_status`, `update_by`, `update_date` in the Completed path.

## Globals and session

Session pid; `$_REQUEST['docid']`, `$_GET['docUpdateId']`; global `num_of_messages_displayed`,
`messages_due_date`.

## Findings

| ID | Sev | Lines | Finding |
|---|---|---|---|
| PNF-01 | Medium | L22-24 | **Write before authorization.** "Completed" is processed before the notes ACL and squad check, and needs no write permission. |
| PNF-02 | Low | L62-73, L92 | **Malformed table.** `</thead>` comes before `</tr>`; `</tbody>` is emitted inside the loop, after every row. |
| PNF-03 | Low | L80 | **Unquoted `id` attribute.** |
| PNF-04 | Low | L19 | **`0 + $_REQUEST['docid']`** throws a TypeError on a non-numeric value under PHP 8. |

## What the port keeps

Messages are outside the brief's required set. If added later: newest N active notes with the
routing prefix stripped, N from the global `num_of_messages_displayed`.
