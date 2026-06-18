# Import Lot Allocation for Odoo 16

This module adds a commercial Import Lot layer for incoming supply and sales allocation.

## Main concept

- `stock.lot`: standard Odoo physical traceability lot.
- `import.lot`: commercial/supply lot created from or related to a Purchase Order.
- `import.lot.allocation`: logical allocation from an Import Lot line to a Sale Order line.

The Import Lot reference uses the Purchase Order number when created from a PO, for example:

- `P00045`
- `P00045-L02`
- `P00045-L03`

## Functional changes in this version

1. Sale Order confirmation does **not** validate whether an Import Lot exists.
2. Import Lot validation is performed only when validating an outgoing picking.
3. If an outgoing picking or its sale lines are linked to Import Lot allocations, the module blocks validation when the related allocation is pending or in exception.
4. If the outgoing picking is explicitly linked to an Import Lot, sale lines must have enough received allocation from that same Import Lot.
5. Physical stock is still controlled by standard Odoo inventory logic.

## Included models

- `import.lot`
- `import.lot.line`
- `import.lot.allocation`

## Installation

1. Copy the `import_lot_allocation` folder to your Odoo addons path.
2. Update the Apps list.
3. Install **Import Lot Allocation**.

## Notes

This module does not modify packages, Odoo stock lots, or quants. It is intended as a commercial allocation/reference layer for import/supply planning.


## Rework Menu Security

This version adds a dedicated security category and groups:

- Rework User
- Rework Manager

Only users assigned to Rework User or Rework Manager can see the root Rework app menu.
The root menu is marked with a web icon so it appears in the Odoo app switcher / app center.
