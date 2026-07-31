# Data Model

All data is local and deterministic.

## Core records

- Product: barcode, SKU, category, variant, price, stock, confidence, location, compatibility tags and conversion reference.
- Room: identifier, occupancy/reset/assistance state, duration and customer context.
- Request: room, product variant, age, priority and fulfilment status.
- Associate: role, active workload and capacity.
- Fulfilment input: capacity, queue length, stock confidence, route, timing preference, accessibility, companion, batch and external availability signals.

The fulfilment engine returns ranked enabled methods with a customer-safe explanation and an estimate. Retailer configuration supplies capacity thresholds, batch window, maximum promise and minimum stock confidence.
