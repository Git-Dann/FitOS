export type StockConfidence = "Confirmed" | "Likely" | "Check";
export type Product = {
  name: string; category: string; barcode: string; sku: string; size: string; colour: string;
  price: number; stock: number; confidence: StockConfidence; location: string; tags: string[]; conversion: number;
};
export type Room = { id: number; state: "Free" | "Occupied" | "Reset" | "Assisted"; customer?: string; minutes?: number };
export type Request = { id: string; room: number; item: string; detail: string; age: number; priority: "Now" | "Next" | "Queue"; status: "Open" | "Picking" | "Delivered" };
export type Scenario = "Quiet Store" | "Busy Saturday" | "Stock Discrepancy" | "Batch Pick" | "Companion Collection";

export const scenarios: Scenario[] = ["Quiet Store", "Busy Saturday", "Stock Discrepancy", "Batch Pick", "Companion Collection"];

export const products: Product[] = [
  { name: "White Heavyweight Tee", category: "Tee", barcode: "5061048301128", sku: "TEE-ST-001", size: "M", colour: "White", price: 42, stock: 14, confidence: "Confirmed", location: "Floor A · Rail 04", tags: ["casual", "layering"], conversion: 61 },
  { name: "Textured Overshirt", category: "Overshirt", barcode: "5061048301197", sku: "OS-TE-014", size: "M", colour: "Olive", price: 95, stock: 6, confidence: "Confirmed", location: "Floor B · Rail 12", tags: ["layering", "smart casual"], conversion: 54 },
  { name: "Field Jacket", category: "Jacket", barcode: "5061048301272", sku: "JK-FD-022", size: "M", colour: "Stone", price: 160, stock: 2, confidence: "Likely", location: "Stockroom · Bay 3", tags: ["outerwear", "utility"], conversion: 47 },
  { name: "Relaxed Selvedge Jean", category: "Jeans", barcode: "5061048301302", sku: "JN-RS-031", size: "32", colour: "Indigo", price: 125, stock: 8, confidence: "Confirmed", location: "Floor C · Wall 02", tags: ["denim", "casual"], conversion: 58 },
  { name: "Pleated Chino", category: "Chinos", barcode: "5061048301357", sku: "CH-PL-041", size: "32", colour: "Charcoal", price: 89, stock: 3, confidence: "Check", location: "Stockroom · Bay 7", tags: ["smart casual", "tailoring"], conversion: 44 },
  { name: "Court Trainer", category: "Trainers", barcode: "5061048301418", sku: "TR-CT-008", size: "9", colour: "White / Green", price: 110, stock: 11, confidence: "Confirmed", location: "Floor D · Wall 01", tags: ["footwear", "casual"], conversion: 63 },
];

export const associates = [
  { name: "Leah K.", role: "Fitting rooms", active: 4, capacity: 6, state: "Available" },
  { name: "Ravi S.", role: "Floor support", active: 5, capacity: 6, state: "Picking" },
  { name: "Amelia B.", role: "Fitting rooms", active: 2, capacity: 6, state: "Available" },
  { name: "Noah D.", role: "Stockroom", active: 6, capacity: 6, state: "At capacity" },
];

export const rooms: Room[] = Array.from({ length: 32 }, (_, i) => {
  const id = i + 1;
  if ([2, 5, 7, 11, 14, 16, 20, 23].includes(id)) return { id, state: "Occupied", customer: `Guest ${String.fromCharCode(65 + (i % 8))}`, minutes: 8 + (i % 5) * 3 };
  if ([4, 18].includes(id)) return { id, state: "Assisted", customer: `Guest ${String.fromCharCode(65 + (i % 8))}`, minutes: 3 };
  if ([9, 27, 30].includes(id)) return { id, state: "Reset" };
  return { id, state: "Free" };
});

export const requests: Request[] = [
  { id: "FR-204", room: 5, item: "Textured Overshirt", detail: "M · Olive", age: 2, priority: "Now", status: "Open" },
  { id: "FR-205", room: 11, item: "Relaxed Selvedge Jean", detail: "32 · Indigo", age: 5, priority: "Now", status: "Picking" },
  { id: "FR-206", room: 14, item: "Court Trainer", detail: "9 · White / Green", age: 3, priority: "Next", status: "Open" },
  { id: "FR-207", room: 20, item: "Pleated Chino", detail: "32 · Navy", age: 7, priority: "Queue", status: "Open" },
];
