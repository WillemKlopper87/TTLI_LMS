/**
 * Display formatters shared by the public storefront (landing, catalogue,
 * course detail, podcasts).
 *
 * There was no shared formatter module before this: every page did its own
 * `Number(x).toLocaleString()` and its own minutes→hours arithmetic, which
 * is why prices rendered three different ways. The prototype fixes both
 * shapes — `R2,450` and `4h 20m` — so they live here once.
 *
 * Everything here degrades to `null`/"" rather than printing "null",
 * "NaN" or "0m": the presentation columns (level/topic/format/
 * estimated_minutes/price) are all nullable on `GET /public/courses`, and
 * a demo course with none of them set must simply render fewer parts.
 */

// en-US, deliberately, not en-ZA: the prototype's price is "R2,450" and
// en-ZA's ICU data groups with a space and separates decimals with a
// comma ("R2 450,00"). The symbol is South African, the grouping is not.
const GROUPING_LOCALE = "en-US";

const CURRENCY_SYMBOLS: Record<string, string> = {
  ZAR: "R",
  USD: "$",
  EUR: "€",
  GBP: "£",
};

/**
 * `R2,450` when the amount is whole, `R2,450.75` when it is not.
 * Amounts arrive from the API as decimal strings.
 */
export function formatMoney(amount: string | number | null | undefined, currency = "ZAR"): string {
  if (amount === null || amount === undefined || amount === "") return "";
  const value = typeof amount === "number" ? amount : Number(amount);
  if (!Number.isFinite(value)) return "";
  const fractionDigits = Number.isInteger(value) ? 0 : 2;
  const body = value.toLocaleString(GROUPING_LOCALE, {
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
  });
  const symbol = CURRENCY_SYMBOLS[currency.toUpperCase()];
  return symbol ? `${symbol}${body}` : `${currency} ${body}`;
}

/** "4h 20m", "3h", "45m" — `null` when there is nothing to say. */
export function formatDuration(minutes: number | null | undefined): string | null {
  if (minutes === null || minutes === undefined) return null;
  const total = Math.round(minutes);
  if (!Number.isFinite(total) || total <= 0) return null;
  const hours = Math.floor(total / 60);
  const rest = total % 60;
  if (hours === 0) return `${rest}m`;
  return rest === 0 ? `${hours}h` : `${hours}h ${rest}m`;
}

/** Player clock: "07:04", "1:02:11". `-` when the media has no duration yet. */
export function formatClock(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds) || seconds < 0) {
    return "--:--";
  }
  const whole = Math.floor(seconds);
  const hours = Math.floor(whole / 3600);
  const minutes = Math.floor((whole % 3600) / 60);
  const secs = whole % 60;
  const mm = hours > 0 ? String(minutes).padStart(2, "0") : String(minutes).padStart(2, "0");
  return hours > 0 ? `${hours}:${mm}:${String(secs).padStart(2, "0")}` : `${mm}:${String(secs).padStart(2, "0")}`;
}

const LEVEL_LABELS: Record<string, string> = {
  introductory: "Introductory",
  intermediate: "Intermediate",
  executive: "Executive",
};

const FORMAT_LABELS: Record<string, string> = {
  self_paced: "Self-paced",
  blended: "Blended",
  live_cohort: "Live cohort",
};

/** `COURSE_LEVEL_VALUES` → display. Unknown/absent values give `null`. */
export function formatLevel(level: string | null | undefined): string | null {
  if (!level) return null;
  return LEVEL_LABELS[level] ?? capitalise(level);
}

/** `COURSE_FORMAT_VALUES` → display. Unknown/absent values give `null`. */
export function formatFormat(format: string | null | undefined): string | null {
  if (!format) return null;
  return FORMAT_LABELS[format] ?? capitalise(format.replace(/_/g, " "));
}

function capitalise(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

/** "6 modules", "1 module", `null` at zero — the card/curriculum meta
 * lines drop the part entirely rather than printing "0 modules". */
export function countLabel(count: number | null | undefined, noun: string): string | null {
  if (count === null || count === undefined || !Number.isFinite(count) || count <= 0) return null;
  return `${count} ${count === 1 ? noun : `${noun}s`}`;
}

/** The `<small>` under a price: the prototype's "incl. VAT". */
export function vatSuffix(includesVat: boolean | null | undefined): string {
  return includesVat ? "incl. VAT" : "excl. VAT";
}

/** The buybox's VAT line: "Includes VAT at 15% · ZAR" / "Excludes VAT · ZAR". */
export function vatLine(includesVat: boolean | null | undefined, currency: string): string {
  return joinMeta([includesVat ? "Includes VAT at 15%" : "VAT added at checkout", currency]);
}

/** Joins the parts of an eyebrow/meta line, dropping the empty ones. */
export function joinMeta(parts: Array<string | null | undefined>): string {
  return parts.filter((part): part is string => Boolean(part)).join(" · ");
}

/* --- Date and clock helpers (the Learn journey's dashboard, player and
   certificate all render dates; kept here so there is one formatter
   module rather than one per route group). --- */

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("en-ZA", { day: "2-digit", month: "short", year: "numeric" });
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("en-ZA", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** "Wednesday" — the dashboard's eyebrow above the greeting. */
export function weekdayLabel(date: Date = new Date()): string {
  return date.toLocaleDateString("en-ZA", { weekday: "long" });
}
