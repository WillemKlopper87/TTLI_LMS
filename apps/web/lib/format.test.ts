/**
 * F13 (BACKLOG.md): admin, account and transcript pages each formatted
 * money and dates themselves — three different money shapes ("R12,450",
 * "ZAR 12,450", "R12,450.00") and five date/time shapes, several of them
 * browser-locale dependent (no locale argument at all). These pin the one
 * shared convention the pages now call.
 */
import { describe, expect, it } from "vitest";

import {
  formatDate,
  formatMoney,
  formatMoneyList,
  formatNumber,
  formatTime,
  formatTimestamp,
} from "@/lib/format";

describe("formatMoney", () => {
  it("drops decimals for whole amounts and keeps them otherwise", () => {
    expect(formatMoney("12450")).toBe("R12,450");
    expect(formatMoney("12450.5")).toBe("R12,450.50");
  });

  it("always shows two decimals when exact, for invoices and finance tables", () => {
    expect(formatMoney("12450", "ZAR", { exact: true })).toBe("R12,450.00");
    expect(formatMoney(0, "ZAR", { exact: true })).toBe("R0.00");
  });

  it("uses the code as a prefix for currencies with no symbol mapping", () => {
    expect(formatMoney(100, "CHF")).toBe("CHF 100");
  });

  it("renders nothing for a missing or unparseable amount", () => {
    expect(formatMoney(null)).toBe("");
    expect(formatMoney("abc")).toBe("");
  });
});

describe("formatMoneyList", () => {
  it("joins per-currency totals with a middle dot, using the shared money shape", () => {
    expect(
      formatMoneyList([
        { currency: "ZAR", amount: "12450" },
        { currency: "USD", amount: "99.5" },
      ]),
    ).toBe("R12,450 · $99.50");
  });

  it("shows an em dash for an empty list rather than a blank cell", () => {
    expect(formatMoneyList([])).toBe("—");
  });
});

describe("formatNumber", () => {
  it("groups with the same convention as money, not the browser locale", () => {
    expect(formatNumber(12450)).toBe("12,450");
    expect(formatNumber(0)).toBe("0");
  });

  it("renders nothing meaningful as a dash", () => {
    expect(formatNumber(null)).toBe("—");
    expect(formatNumber(Number.NaN)).toBe("—");
  });
});

describe("formatTimestamp", () => {
  it("includes the year and time, unlike formatDateTime, for audit-style rows", () => {
    const out = formatTimestamp("2026-09-19T14:05:00Z");
    expect(out).toMatch(/2026/);
    expect(out).toMatch(/Sep/);
    expect(out).toMatch(/\d{2}:\d{2}/);
  });

  it("degrades to a dash for missing or invalid input", () => {
    expect(formatTimestamp(null)).toBe("—");
    expect(formatTimestamp("not a date")).toBe("—");
  });
});

describe("formatDate", () => {
  it("is the day-month-year shape the raw call sites hand-rolled", () => {
    // en-ZA's ICU data abbreviates September as "Sept", so match the stem.
    expect(formatDate("2026-09-19T14:05:00Z")).toMatch(/^19 Sep\w* 2026$/);
  });
});

describe("formatTime", () => {
  it("is a 24-hour clock for booking slots", () => {
    expect(formatTime("2026-09-19T14:05:00Z")).toMatch(/^\d{2}:\d{2}$/);
  });

  it("degrades to a dash for missing or invalid input", () => {
    expect(formatTime(null)).toBe("—");
    expect(formatTime("nope")).toBe("—");
  });
});
