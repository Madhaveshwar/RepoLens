/**
 * Central date/time formatting utility — the ONLY place in the app where
 * timestamps are formatted for display.
 *
 * TIMEZONE STRATEGY (matches the backend contract):
 *  - Backend stores naive UTC datetimes and now serializes them as
 *    timezone-aware ISO 8601 UTC strings, e.g. "2026-09-24T18:23:41Z".
 *  - new Date("...Z") is parsed by JavaScript as UTC and all accessor
 *    methods (toLocaleString etc.) render in the BROWSER's local timezone.
 *    India (UTC+5:30) → 24 Sep 2026, 11:53 PM. No manual hour arithmetic,
 *    no double conversion, no hardcoded timezone.
 *  - Legacy safety: if a timestamp ever arrives WITHOUT a timezone marker
 *    (e.g. cached old data), we treat it as UTC explicitly — matching how
 *    the database actually stores it — by appending "Z" before parsing.
 *    Values already carrying "Z" or an offset are never touched.
 */

export type DateFormat = "datetime" | "datetime-seconds" | "date" | "time";

/** Normalize any API timestamp into a JS Date interpreted in UTC when the
 *  string carries no timezone marker. Returns null for null/empty/invalid. */
export function parseTimestamp(value: string | Date | null | undefined): Date | null {
  if (!value) return null;
  if (value instanceof Date) return isNaN(value.getTime()) ? null : value;
  const raw = String(value).trim();
  if (!raw) return null;
  // Already unambiguous (Z suffix or ±HH:MM offset) → parse as-is.
  if (/[Zz]$/.test(raw) || /[+-]\d{2}:?\d{2}$/.test(raw)) {
    const d = new Date(raw);
    return isNaN(d.getTime()) ? null : d;
  }
  // Timezone-less ISO string (legacy serialization) → it is UTC by contract.
  const d = new Date(`${raw}Z`);
  return isNaN(d.getTime()) ? null : d;
}

/**
 * Format a timestamp for display in the user's local timezone.
 *
 * Default:  "24 Sep 2026, 11:55 PM"
 * Detailed: "24 Sep 2026, 11:55:42 PM" (with seconds)
 * Date:     "24 Sep 2026"
 * Time:     "11:55 PM"
 */
export function formatDateTime(
  value: string | Date | null | undefined,
  format: DateFormat = "datetime"
): string {
  const d = parseTimestamp(value);
  if (!d) return "Not available";

  const datePart = d.toLocaleDateString(undefined, {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
  const timePart = d.toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
    ...(format === "datetime-seconds" || format === "time" ? { second: "2-digit" } : {}),
    hour12: true,
  });

  switch (format) {
    case "date":
      return datePart;
    case "time":
      return timePart;
    case "datetime-seconds":
      return `${datePart}, ${timePart}`;
    case "datetime":
    default:
      return `${datePart}, ${timePart}`;
  }
}

/** Short form for compact surfaces: "24 Sep 2026, 11:55 PM" (same as default,
 *  kept as an alias so call sites read clearly). */
export const formatTimestamp = formatDateTime;

/** Date-only label: "24 Sep 2026". */
export function formatDate(value: string | Date | null | undefined): string {
  return formatDateTime(value, "date");
}

/** Relative label for secondary text, e.g. "2 minutes ago". */
export function formatRelative(value: string | Date | null | undefined): string {
  const d = parseTimestamp(value);
  if (!d) return "";
  const diffMs = Date.now() - d.getTime();
  const past = diffMs >= 0;
  const secs = Math.floor(Math.abs(diffMs) / 1000);
  const mins = Math.floor(secs / 60);
  const hours = Math.floor(mins / 60);
  const days = Math.floor(hours / 24);

  let label: string;
  if (secs < 60) label = "just now";
  else if (mins < 60) label = `${mins} minute${mins === 1 ? "" : "s"}`;
  else if (hours < 24) label = `${hours} hour${hours === 1 ? "" : "s"}`;
  else label = `${days} day${days === 1 ? "" : "s"}`;

  if (label === "just now") return label;
  return past ? `${label} ago` : `in ${label}`;
}
