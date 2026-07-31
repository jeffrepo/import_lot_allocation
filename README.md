# Import Lot Allocation - Odoo 16

This module adds an Import Lot flow for purchase/sale allocation, stock Rework, and planned delivery packages.

## Included changes

- `import.lot`, `import.lot.line`, `import.lot.allocation` models.
- Purchase Order button: **Create Import Lot**.
- Import Lot reference based on PO number: `P00001`, `P00001-L02`, etc.
- Sale Orders can be confirmed freely.
- Delivery validation checks Import Lot only at picking validation time.
- A PO reserves one future package reference with exactly the PO number before stock is received.
- Incoming receipts linked to an Import Lot are forced into that PO-numbered package, even if Odoo already proposed a `PACK...` package.
- On upgrade, an unambiguous existing receipt package is linked to its PO reference and renamed from `PACK...` to the PO number.
- Incoming receipt move lines are filled with `qty_done` when empty.
- Sale Order lines select an existing Import Lot; the delivery plan is created automatically.
- A physical package is created only when the outgoing transfer is completed.
- Every partial delivery/backorder creates a different physical package.
- One Rework Order belongs to one Sale Order and contains multiple conversion lines.
- Each line can consume all or part of product A and add product B to the same purchased package.
- A Rework can select a PO/Import Lot while it is in transit. Confirming creates the empty physical package with the PO number; processing waits for its receipt.
- Rework output can be reserved for a specific Sale Order without purchasing product B.
- A partial Rework keeps one Sale Order line and splits only its outgoing stock moves between Rework and normal stock.
- Products manually added or removed on open receipts/deliveries are synchronized to their Purchase/Sale Orders.
- Import Lot line changes synchronize back to the Purchase Order lines when the PO is not done/cancelled.
- `company_id` view validation fix for non-multi-company users.
- Rework menu groups: Rework User / Rework Manager.

## Package-based flow

The implementation now uses `stock.quant.package` as the physical grouping reference.

- Import Lot = commercial/supply reference, usually the PO number.
- Future package = transitory reference reserved from a PO, with exactly the PO number.
- Incoming package = physical grouping created from the future reference on Rework confirmation or receipt validation.
- Planned package = internal non-physical delivery grouping created automatically from the selected Import Lot.
- Physical delivery package = `stock.quant.package` created when the outgoing stock move is done.
- Reworked package = the original physical source package, now containing the remaining source product and the converted product.
- Products should be configured with **No Tracking** if the customer wants everything by package instead of `stock.lot`.

If a product is configured with tracking by lots/serial numbers, Odoo standard will still require `stock.lot` during receipt/delivery.

## Recommended flow

1. Confirm PO.
2. Click **Create Import Lot**.
3. The module reserves future package `P00001`; no physical package or stock is created yet.
4. Optionally create and confirm the Sale Order Rework while the PO is still in transit.
   - Each conversion line selects the source PO/Import Lot.
   - Confirmation creates the empty physical package `P00001`.
   - Processing remains blocked until enough source stock has been received.
5. Validate incoming receipt.
   - The module creates or reuses package `P00001`.
   - Any automatically proposed `PACK...` is replaced on the receipt lines by `P00001`.
   - The module assigns `result_package_id` and `qty_done` on receipt lines.
6. Select the existing **Import Lot** on each applicable Sale Order line.
   - The module creates the commercial allocation for the ordered quantity.
   - The module creates/reuses one internal plan per Sale Order and Import Lot.
7. Confirm the Sale Order; the Import Lot's internal plan is copied to its open stock moves.
8. Validate the delivery.
   - The module creates a physical package at the final stock operation.
   - The package is assigned through `result_package_id`.
   - A later backorder validation creates another physical package.

## Purchase synchronization

When users edit Import Lot expected lines:

- Existing linked PO lines are updated.
- New Import Lot products create new PO lines.
- Lines cannot be reduced below quantities already received.
- Done/cancelled POs are not modified.

## Import Lot per Sale Order Line

Outgoing packages have two separate stages so users can adjust Sale Order quantities without creating empty physical packages.

- Incoming receipts can still use `Import Lot` on the receipt. Validation creates or reuses a physical package with the Import Lot reference and receives products into that package.
- Sale Order lines select the existing `Import Lot`, not a manually created plan.
- The module maintains a persistent `Planned Package` internally; it does not affect physical inventory.
- Selecting an Import Lot automatically reserves the Sale Order line quantity through `import.lot.allocation`.
- When the Sale Order is confirmed, the plan is copied to generated stock moves.
- Updating the Import Lot or quantity on a Sale Order line updates its automatic allocation and open stock moves.
- When an outgoing move is actually completed, the module creates one physical package per planned package and picking.
- Partial deliveries keep the plan on the backorder and create a new physical package when that backorder is completed.
- Legacy manually assigned packages are not treated as delivery plans. A Rework result package is enforced as the physical source for its delivery.

## Rework A to B

Rework Orders are available from **Rework → Rework Orders**.

Example: PO `P00001` will receive Lemon A, and part of it must become Lemon B and Lemon C for one Sale Order.

1. Open the Sale Order and use its **Rework** smart button. The same active Rework is reused.
2. Add a conversion line and select the source PO / future package `P00001` even if it is still in transit.
3. Select source product Lemon A, quantity to consume `0.5`, result product Lemon B, quantity to generate `5`, and the Lemon B Sale Order line.
4. Add any other product conversions required by the same Sale Order as additional lines.
5. Click **Confirm**.
   - If necessary, the module creates an empty physical package named exactly `P00001`.
   - Each result line gets its own internal Import Lot without a Purchase Order, restricted to the selected Sale Order.
   - Every selected Sale Order line keeps its original quantity and is not duplicated.
   - Rework quantities receive partial allocations immediately, before the result products exist physically.
   - At stock level, only that quantity receives the Rework package plan; the remainder can use normal stock.
6. Validate the PO receipt. All products are received into package `P00001`.
7. Click **Process Rework**.
   - Two auditable stock moves are created for every conversion line.
   - A stock move consumes 0.5 Lemon A from package `P00001` into the Production location.
   - A second stock move produces 5 Lemon B back into package `P00001`.
   - Package `P00001` keeps the unconsumed Lemon A and contains all converted products.
   - No additional physical package is created.
   - Result Import Lots become received and their internal delivery plans point to package `P00001`.
8. Validate the Sale Order delivery.
   - The delivery consumes Lemon B specifically from the original, reworked package.
   - The final customer package is still created only when the delivery is validated.

The source product UoM must allow the desired decimal precision when only part of one unit is consumed
(for example, a rounding of `0.01`). The simple Rework flow supports products configured with **No Tracking**.

## Transfer-to-order synchronization

- Adding a new product to an open incoming receipt creates and links a new Purchase Order line.
- If that receipt has an Import Lot, its expected line is created as well.
- Adding a new product to an open outgoing delivery creates and links a new Sale Order line.
- Removing the only remaining stock move for an undelivered/unreceived, uninvoiced order line removes that order line too.
- Received, delivered, or invoiced lines are protected from reverse deletion.

Products tracked by serial or stock lot require a separate lot/serial assignment flow.

This lightweight flow records auditable stock consumption and production moves but does not calculate the
result product cost from the consumed product. The result product therefore uses its configured inventory cost.
