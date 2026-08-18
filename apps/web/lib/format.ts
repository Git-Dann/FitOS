/**
 * Formatting, in one place.
 *
 * docs/design-system.md §10 makes a formatted currency or percentage literal
 * anywhere in `apps/web` outside a fixture a build failure. This module is why
 * that rule is livable: components ask for a formatted string, they never build
 * one. It is also the reason a currency change is one edit rather than a search.
 *
 * Money arrives as integer minor units, exactly as the aggregate stores it, and
 * is divided here and nowhere else. A component that divides by 100 is a
 * component that will eventually divide by 100 twice.
 */

const LOCALE = "en-GB";

/** Minor units to a display string. Never called with a float. */
export function money(minor: number, currency: string): string {
  return new Intl.NumberFormat(LOCALE, {
    style: "currency",
    currency,
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(minor / 100);
}

/**
 * An exposure range, always as a range.
 *
 * gap-model.md §3: never present a single precise financial value when the
 * inputs do not support that precision. A lone base figure reads as precision
 * the model does not have, so this returns low–high and the base is shown
 * separately, adjacent to its confidence.
 */
export function exposureRange(low: number, high: number, currency: string): string {
  if (low === high) return money(low, currency);
  return `${money(low, currency)}–${money(high, currency)}`;
}

export function ratio(value: number, fractionDigits = 0): string {
  return new Intl.NumberFormat(LOCALE, {
    style: "percent",
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
  }).format(value);
}

export function count(value: number): string {
  return new Intl.NumberFormat(LOCALE).format(value);
}

/**
 * A duration as an age. Coarse on purpose: "2h" is what a triager needs, and
 * "2h 14m 06s" is noise that changes every second in a screenshot.
 */
export function age(seconds: number): string {
  if (seconds < 60) return `${Math.floor(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 172_800) return `${Math.floor(seconds / 3600)}h`;
  return `${Math.floor(seconds / 86_400)}d`;
}

/**
 * Age of a timestamp against a fixed reference.
 *
 * The reference is passed in rather than read from the clock, so the ledger
 * renders identically on every load. A demo whose ages drift cannot be
 * screenshot-reviewed, and reduced-motion users see values change under them.
 */
export function ageSince(iso: string, asOfIso: string): string {
  const seconds = (Date.parse(asOfIso) - Date.parse(iso)) / 1000;
  return age(Math.max(0, seconds));
}

/** Short date for a first-seen column. */
export function shortDate(iso: string): string {
  return new Intl.DateTimeFormat(LOCALE, { day: "2-digit", month: "short" }).format(new Date(iso));
}

export function dateTime(iso: string): string {
  return new Intl.DateTimeFormat(LOCALE, {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
    timeZoneName: "short",
  }).format(new Date(iso));
}

/** `stock_truth_mismatch` → `Stock truth mismatch`, for reason codes. */
export function humanise(key: string): string {
  const spaced = key.replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}
