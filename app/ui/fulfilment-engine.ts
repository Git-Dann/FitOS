export type CapacityState = "Green" | "Amber" | "Red";
export type StockConfidence = "Confirmed" | "Likely" | "Check";
export type Method = "Staff delivery now" | "Companion collection" | "Customer self-collection" | "Batch pick" | "Bring before I finish" | "Collect at checkout" | "Reserve nearby" | "Home delivery" | "Alternative product" | "Unable to fulfil";

export type RetailerConfig = {
  enabledMethods: Method[];
  queueThresholds: { amber: number; red: number };
  batchWindowMinutes: number;
  maximumPromiseMinutes: number;
  minimumStockConfidence: StockConfidence;
};

export type FulfilmentInput = {
  capacity: CapacityState;
  activeAssociates: number;
  queueLength: number;
  companionPresent: boolean;
  location: "Shop floor" | "Stockroom";
  stockConfidence: StockConfidence;
  stockUnits: number;
  walkingMinutes: number;
  timingPreference: "As soon as possible" | "Before I finish" | "No rush";
  accessibilityNeed: boolean;
  batchOpportunity: boolean;
  onlineAvailable: boolean;
  nearbyStoreAvailable: boolean;
};

export type FulfilmentOption = { method: Method; score: number; estimate: string; explanation: string; available: boolean };

export const defaultRetailerConfig: RetailerConfig = {
  enabledMethods: ["Staff delivery now", "Companion collection", "Customer self-collection", "Batch pick", "Bring before I finish", "Collect at checkout", "Reserve nearby", "Home delivery", "Alternative product"],
  queueThresholds: { amber: 5, red: 10 },
  batchWindowMinutes: 8,
  maximumPromiseMinutes: 12,
  minimumStockConfidence: "Likely",
};

const confidenceRank: Record<StockConfidence, number> = { Confirmed: 3, Likely: 2, Check: 1 };
const isEnabled = (method: Method, config: RetailerConfig) => config.enabledMethods.includes(method);
const usableStock = (input: FulfilmentInput, config: RetailerConfig) => input.stockUnits > 0 && confidenceRank[input.stockConfidence] >= confidenceRank[config.minimumStockConfidence];
const estimate = (minutes: number, config: RetailerConfig) => minutes <= config.maximumPromiseMinutes ? `About ${minutes} min` : "Timing will be confirmed";

export function rankFulfilment(input: FulfilmentInput, config: RetailerConfig = defaultRetailerConfig): FulfilmentOption[] {
  const options: FulfilmentOption[] = [];
  const stockReady = usableStock(input, config);
  const directMinutes = Math.max(2, input.walkingMinutes + (input.location === "Stockroom" ? 3 : 1));
  const add = (method: Method, score: number, minutes: number, explanation: string, available = true) => {
    if (isEnabled(method, config) && available) options.push({ method, score, estimate: estimate(minutes, config), explanation, available });
  };

  if (stockReady) {
    const staffAllowed = input.capacity !== "Red" || input.accessibilityNeed;
    add("Staff delivery now", input.capacity === "Green" ? 98 : input.capacity === "Amber" ? 63 : 82, directMinutes, input.accessibilityNeed ? "Prioritised to support your accessibility need." : input.capacity === "Green" ? "A colleague can bring a confirmed item to your room now." : "Available with an estimated delivery time based on current floor activity.", staffAllowed);
    add("Companion collection", input.companionPresent ? (input.capacity === "Green" ? 76 : 91) : 0, directMinutes, "Your companion can collect a confirmed item while you keep trying on.", input.companionPresent);
    add("Customer self-collection", input.capacity === "Red" ? 74 : 48, directMinutes, "The item can be collected from a nearby point when it suits you.");
    add("Batch pick", input.batchOpportunity ? (input.capacity === "Amber" ? 88 : 70) : 0, directMinutes + config.batchWindowMinutes, `This item can travel with another pick in the next ${config.batchWindowMinutes}-minute collection window.`, input.batchOpportunity);
    add("Bring before I finish", input.timingPreference === "Before I finish" ? 86 : 42, directMinutes + 3, "The request is timed to arrive before you finish your current fitting-room session.");
    add("Collect at checkout", input.timingPreference === "No rush" ? 75 : 45, directMinutes + 5, "The item can be held for collection when you reach checkout.");
  }
  if (input.nearbyStoreAvailable) add("Reserve nearby", stockReady ? 39 : 81, 0, "A nearby store has an option that can be reserved for you.");
  if (input.onlineAvailable) add("Home delivery", stockReady ? 31 : 77, 0, "This option is available for home delivery after your fitting-room visit.");
  if (!stockReady) add("Alternative product", 96, 0, input.stockUnits === 0 ? "The requested item is unavailable here; a similar option is available sooner." : "The requested item needs a stock check; a similar option can be considered sooner.");
  if (!options.length) options.push({ method: "Unable to fulfil", score: 1, estimate: "Unavailable", explanation: "No enabled fulfilment route is currently available for this request.", available: true });
  return options.sort((a, b) => b.score - a.score);
}

export function capacityFromQueue(queueLength: number, config: RetailerConfig): CapacityState {
  if (queueLength >= config.queueThresholds.red) return "Red";
  if (queueLength >= config.queueThresholds.amber) return "Amber";
  return "Green";
}
