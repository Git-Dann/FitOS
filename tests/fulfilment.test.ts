import assert from "node:assert/strict";
import test from "node:test";
import { defaultRetailerConfig, rankFulfilment, type FulfilmentInput } from "../app/ui/fulfilment-engine";

const input = (overrides: Partial<FulfilmentInput> = {}): FulfilmentInput => ({
  capacity: "Green", activeAssociates: 4, queueLength: 2, companionPresent: false,
  location: "Shop floor", stockConfidence: "Confirmed", stockUnits: 6, walkingMinutes: 2,
  timingPreference: "As soon as possible", accessibilityNeed: false, batchOpportunity: false,
  onlineAvailable: true, nearbyStoreAvailable: true, ...overrides,
});

test("green capacity favours immediate staff delivery for confirmed floor stock", () => {
  const results = rankFulfilment(input());
  assert.equal(results[0].method, "Staff delivery now");
  assert.match(results[0].explanation, /confirmed item/);
});

test("amber capacity promotes companion collection and batch opportunities", () => {
  const companion = rankFulfilment(input({ capacity: "Amber", companionPresent: true, location: "Stockroom", walkingMinutes: 4, batchOpportunity: true }));
  assert.equal(companion[0].method, "Companion collection");
  const batch = rankFulfilment(input({ capacity: "Amber", companionPresent: false, location: "Stockroom", walkingMinutes: 4, batchOpportunity: true }));
  assert.equal(batch[0].method, "Batch pick");
});

test("red capacity limits immediate delivery but protects accessibility needs", () => {
  const restricted = rankFulfilment(input({ capacity: "Red" }));
  assert.notEqual(restricted[0].method, "Staff delivery now");
  const protectedRoute = rankFulfilment(input({ capacity: "Red", accessibilityNeed: true }));
  assert.equal(protectedRoute[0].method, "Staff delivery now");
  assert.match(protectedRoute[0].explanation, /accessibility need/);
});

test("uncertain or unavailable stock promotes alternative and external options", () => {
  const results = rankFulfilment(input({ stockConfidence: "Check", stockUnits: 2 }));
  assert.equal(results[0].method, "Alternative product");
  assert.ok(results.some(option => option.method === "Reserve nearby"));
  assert.ok(results.some(option => option.method === "Home delivery"));
});

test("retailer policy can disable a method and raise the confidence threshold", () => {
  const config = { ...defaultRetailerConfig, enabledMethods: defaultRetailerConfig.enabledMethods.filter(method => method !== "Staff delivery now"), minimumStockConfidence: "Confirmed" as const };
  const results = rankFulfilment(input({ stockConfidence: "Likely" }), config);
  assert.ok(!results.some(option => option.method === "Staff delivery now"));
  assert.equal(results[0].method, "Alternative product");
});
