# Import Lot Allocation - Odoo 16

This module adds an Import Lot flow for purchase/sale allocation and planned delivery packages.

## Included changes

- `import.lot`, `import.lot.line`, `import.lot.allocation` models.
- Purchase Order button: **Create Import Lot**.
- Import Lot reference based on PO number: `P00001`, `P00001-L02`, etc.
- Sale Orders can be confirmed freely.
- Delivery validation checks Import Lot only at picking validation time.
- Incoming receipts linked to an Import Lot automatically use/create a package named as the Import Lot.
- Incoming receipt move lines are filled with `qty_done` when empty.
- Sale Order lines can be grouped into planned packages without creating physical stock packages in advance.
- A physical package is created only when the outgoing transfer is completed.
- Every partial delivery/backorder creates a different physical package.
- Import Lot line changes synchronize back to the Purchase Order lines when the PO is not done/cancelled.
- `company_id` view validation fix for non-multi-company users.
- Rework menu groups: Rework User / Rework Manager.

## Package-based flow

The implementation now uses `stock.quant.package` as the physical grouping reference.

- Import Lot = commercial/supply reference, usually the PO number.
- Incoming package = physical grouping created when an Import Lot receipt is validated.
- Planned package = non-physical delivery grouping selected on Sale Order lines.
- Physical delivery package = `stock.quant.package` created when the outgoing stock move is done.
- Products should be configured with **No Tracking** if the customer wants everything by package instead of `stock.lot`.

If a product is configured with tracking by lots/serial numbers, Odoo standard will still require `stock.lot` during receipt/delivery.

## Recommended flow

1. Confirm PO.
2. Click **Create Import Lot**.
3. Confirm Import Lot.
4. Validate incoming receipt.
   - The module creates/uses package `P00001`.
   - The module assigns `result_package_id` and `qty_done` on receipt lines.
5. Create planned packages on the Sale Order and select one on each applicable line.
6. Confirm the Sale Order; the planned package is copied to its open stock moves.
7. Validate the delivery.
   - The module creates a physical package at the final stock operation.
   - The package is assigned through `result_package_id`.
   - A later backorder validation creates another physical package.

## Purchase synchronization

When users edit Import Lot expected lines:

- Existing linked PO lines are updated.
- New Import Lot products create new PO lines.
- Lines cannot be reduced below quantities already received.
- Done/cancelled POs are not modified.

## Planned Package per Sale Order Line

Outgoing packages have two separate stages so users can adjust Sale Order quantities without creating empty physical packages.

- Incoming receipts can still use `Import Lot` on the receipt. Validation creates or reuses a physical package with the Import Lot reference and receives products into that package.
- Sale Orders contain persistent `Planned Packages` that do not affect physical inventory.
- Sale Order lines select a `Planned Package`.
- When the Sale Order is confirmed, the plan is copied to generated stock moves.
- The planned package can also be changed directly on an open outgoing stock move.
- Updating the plan on a Sale Order line updates its open stock moves.
- When an outgoing move is actually completed, the module creates one physical package per planned package and picking.
- Partial deliveries keep the plan on the backorder and create a new physical package when that backorder is completed.
- Existing manually assigned source packages are not used as the delivery plan; Odoo standard source reservation remains in control.
