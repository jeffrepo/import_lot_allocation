# Import Lot Allocation - Odoo 16

This module adds an Import Lot flow for purchase/sale allocation and physical stock control by **package**.

## Included changes

- `import.lot`, `import.lot.line`, `import.lot.allocation` models.
- Purchase Order button: **Create Import Lot**.
- Import Lot reference based on PO number: `P00001`, `P00001-L02`, etc.
- Sale Orders can be confirmed freely.
- Delivery validation checks Import Lot only at picking validation time.
- Incoming receipts linked to an Import Lot automatically use/create a package named as the Import Lot.
- Incoming receipt move lines are filled with `qty_done` when empty.
- Outgoing deliveries linked to an Import Lot consume from the package named as the Import Lot.
- Import Lot line changes synchronize back to the Purchase Order lines when the PO is not done/cancelled.
- `company_id` view validation fix for non-multi-company users.
- Rework menu groups: Rework User / Rework Manager.

## Package-based flow

The implementation now uses `stock.quant.package` as the physical grouping reference.

- Import Lot = commercial/supply reference, usually the PO number.
- Package = physical inventory grouping, same name as Import Lot.
- Products should be configured with **No Tracking** if the customer wants everything by package instead of `stock.lot`.

If a product is configured with tracking by lots/serial numbers, Odoo standard will still require `stock.lot` during receipt/delivery.

## Recommended flow

1. Confirm PO.
2. Click **Create Import Lot**.
3. Confirm Import Lot.
4. Validate incoming receipt.
   - The module creates/uses package `P00001`.
   - The module assigns `result_package_id` and `qty_done` on receipt lines.
5. Link outgoing delivery to the Import Lot.
6. Validate delivery.
   - The module validates stock in the package and assigns `package_id` on delivery lines.

## Purchase synchronization

When users edit Import Lot expected lines:

- Existing linked PO lines are updated.
- New Import Lot products create new PO lines.
- Lines cannot be reduced below quantities already received.
- Done/cancelled POs are not modified.

## Package per Sale Order Line

This version moves outgoing package selection from picking-level Import Lot to sale order lines / stock moves.

- Incoming receipts can still use `Import Lot` on the receipt. Validation creates or reuses a physical package with the Import Lot reference and receives products into that package.
- Sale order lines now include `Package` and `Available in Package`.
- When the sale order is confirmed, the selected package is copied to the generated stock move.
- Updating the package on a sale order line updates open stock moves.
- Delivery validation checks package stock per move/product, allowing one delivery to contain different products from different packages.
- The picking-level `Import Lot` is no longer the main outgoing validation source; it remains useful for incoming receipts and legacy reference only.
