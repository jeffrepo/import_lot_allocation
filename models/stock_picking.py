# -*- coding: utf-8 -*-
from odoo import fields, models, _
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    import_lot_id = fields.Many2one(
        'import.lot',
        string='Import Lot',
        index=True,
        tracking=True,
        help='Supply/import lot related to this receipt or transfer. This is not the standard Odoo stock lot.',
    )

    def button_validate(self):
        self._check_import_lot_delivery_rules()
        res = super().button_validate()
        self._update_import_lot_after_receipt()
        return res

    def _check_import_lot_delivery_rules(self):
        """Validate Import Lot rules only at outgoing picking validation time.

        Sale orders can be confirmed with or without Import Lot allocations.
        At delivery validation, Import Lot controls matter only when the delivery or sale line is linked to Import Lot allocations.
        """
        for picking in self.filtered(lambda p: p.picking_type_code == 'outgoing'):
            sale = picking.sale_id
            if not sale:
                continue

            blocking_allocations = sale.order_line.mapped('import_lot_allocation_ids').filtered(
                lambda a: a.state in ('draft', 'reserved', 'exception') and a.pending_qty > 0
            )
            if blocking_allocations:
                details = '\n'.join('- %s: %s %s (%s)' % (
                    a.product_id.display_name,
                    a.pending_qty,
                    a.product_uom_id.name,
                    a.import_lot_id.name,
                ) for a in blocking_allocations)
                raise UserError(_(
                    'You cannot validate this delivery because some Import Lot allocations are still pending or in exception.\n\n%s'
                ) % details)

            if picking.import_lot_id:
                self._check_picking_import_lot_line_coverage(picking)

    def _check_picking_import_lot_line_coverage(self, picking):
        """When the delivery explicitly has an Import Lot, require matching received allocations for its sale lines."""
        errors = []
        valid_states = ('received', 'assigned', 'done')
        for move in picking.move_ids_without_package.filtered(lambda m: m.sale_line_id and m.product_id and m.product_id.detailed_type == 'product'):
            sale_line = move.sale_line_id
            qty_to_deliver = move.quantity_done or move.product_uom_qty
            if not qty_to_deliver:
                continue
            qty_in_sale_uom = move.product_uom._compute_quantity(
                qty_to_deliver,
                sale_line.product_uom,
                rounding_method='HALF-UP',
            )
            allocations = sale_line.import_lot_allocation_ids.filtered(
                lambda a: a.import_lot_id == picking.import_lot_id and a.state in valid_states
            )
            allocated_received = sum(
                allocation.product_uom_id._compute_quantity(
                    allocation.received_qty,
                    sale_line.product_uom,
                    rounding_method='HALF-UP',
                ) for allocation in allocations
            )
            precision = sale_line.product_uom.rounding or 0.01
            if float_compare(allocated_received, qty_in_sale_uom, precision_rounding=precision) < 0:
                errors.append(_(
                    '- %(product)s: delivery quantity %(delivery_qty)s %(uom)s, received allocation in %(lot)s %(allocated)s %(uom)s.'
                ) % {
                    'product': move.product_id.display_name,
                    'delivery_qty': qty_in_sale_uom,
                    'allocated': allocated_received,
                    'lot': picking.import_lot_id.name,
                    'uom': sale_line.product_uom.name,
                })
        if errors:
            raise UserError(_(
                'This delivery is linked to Import Lot %(lot)s, but some sale lines do not have enough received Import Lot allocation.\n\n%(details)s'
            ) % {'lot': picking.import_lot_id.name, 'details': '\n'.join(errors)})

    def _update_import_lot_after_receipt(self):
        for picking in self.filtered(lambda p: p.picking_type_code == 'incoming' and p.import_lot_id):
            lot = picking.import_lot_id
            if lot.state not in ('closed', 'cancelled'):
                if all(line.received_qty >= line.expected_qty for line in lot.line_ids):
                    lot.state = 'received'
                elif any(line.received_qty > 0 for line in lot.line_ids):
                    lot.state = 'partially_received'
