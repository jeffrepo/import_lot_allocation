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
        # For incoming receipts, put all received products into a package named as the Import Lot.
        self._assign_import_lot_package_on_receipt()
        # For outgoing deliveries, consume from the package linked to the Import Lot and validate coverage.
        self._assign_import_lot_package_on_delivery()
        self._check_import_lot_delivery_rules()
        res = super().button_validate()
        self._update_import_lot_after_receipt()
        return res

    def _get_or_create_import_lot_package(self, import_lot, company):
        Package = self.env['stock.quant.package']
        package = Package.search([
            ('name', '=', import_lot.name),
            '|',
            ('company_id', '=', False),
            ('company_id', '=', company.id),
        ], limit=1)
        if not package:
            package = Package.create({
                'name': import_lot.name,
                'company_id': company.id,
            })
        return package

    def _get_move_qty_to_process(self, move):
        qty = move.quantity_done or 0.0
        if not qty:
            qty = move.product_uom_qty or 0.0
        return qty

    def _assign_import_lot_package_on_receipt(self):
        """Use the Import Lot reference as the physical package on receipts.

        This flow intentionally uses packages instead of stock.lot. Products should not require
        lot/serial tracking if the implementation is fully package-based.
        """
        MoveLine = self.env['stock.move.line']
        for picking in self.filtered(lambda p: p.picking_type_code == 'incoming' and p.import_lot_id):
            package = self._get_or_create_import_lot_package(picking.import_lot_id, picking.company_id)
            for move in picking.move_ids_without_package.filtered(lambda m: m.product_id and m.product_id.detailed_type == 'product'):
                qty_to_receive = self._get_move_qty_to_process(move)
                if not qty_to_receive:
                    continue

                if not move.move_line_ids:
                    MoveLine.create({
                        'picking_id': picking.id,
                        'move_id': move.id,
                        'product_id': move.product_id.id,
                        'product_uom_id': move.product_uom.id,
                        'location_id': move.location_id.id,
                        'location_dest_id': move.location_dest_id.id,
                        'qty_done': qty_to_receive,
                        'result_package_id': package.id,
                        'company_id': picking.company_id.id,
                    })
                    continue

                remaining_qty = qty_to_receive
                for move_line in move.move_line_ids.filtered(lambda ml: ml.product_id == move.product_id):
                    if not move_line.qty_done:
                        qty_line = getattr(move_line, 'reserved_uom_qty', 0.0) or remaining_qty
                        move_line.qty_done = qty_line
                    if not move_line.result_package_id:
                        move_line.result_package_id = package.id
                    remaining_qty -= move_line.qty_done

                if float_compare(remaining_qty, 0.0, precision_rounding=move.product_uom.rounding or 0.01) > 0:
                    MoveLine.create({
                        'picking_id': picking.id,
                        'move_id': move.id,
                        'product_id': move.product_id.id,
                        'product_uom_id': move.product_uom.id,
                        'location_id': move.location_id.id,
                        'location_dest_id': move.location_dest_id.id,
                        'qty_done': remaining_qty,
                        'result_package_id': package.id,
                        'company_id': picking.company_id.id,
                    })

    def _assign_import_lot_package_on_delivery(self):
        """When a delivery is linked to an Import Lot, consume from that Import Lot package."""
        MoveLine = self.env['stock.move.line']
        for picking in self.filtered(lambda p: p.picking_type_code == 'outgoing' and p.import_lot_id):
            package = self._get_or_create_import_lot_package(picking.import_lot_id, picking.company_id)
            for move in picking.move_ids_without_package.filtered(lambda m: m.product_id and m.product_id.detailed_type == 'product'):
                qty_to_deliver = self._get_move_qty_to_process(move)
                if not qty_to_deliver:
                    continue

                if not move.move_line_ids:
                    MoveLine.create({
                        'picking_id': picking.id,
                        'move_id': move.id,
                        'product_id': move.product_id.id,
                        'product_uom_id': move.product_uom.id,
                        'location_id': move.location_id.id,
                        'location_dest_id': move.location_dest_id.id,
                        'qty_done': qty_to_deliver,
                        'package_id': package.id,
                        'company_id': picking.company_id.id,
                    })
                    continue

                remaining_qty = qty_to_deliver
                for move_line in move.move_line_ids.filtered(lambda ml: ml.product_id == move.product_id):
                    if not move_line.qty_done:
                        qty_line = getattr(move_line, 'reserved_uom_qty', 0.0) or remaining_qty
                        move_line.qty_done = qty_line
                    if not move_line.package_id:
                        move_line.package_id = package.id
                    remaining_qty -= move_line.qty_done

                if float_compare(remaining_qty, 0.0, precision_rounding=move.product_uom.rounding or 0.01) > 0:
                    MoveLine.create({
                        'picking_id': picking.id,
                        'move_id': move.id,
                        'product_id': move.product_id.id,
                        'product_uom_id': move.product_uom.id,
                        'location_id': move.location_id.id,
                        'location_dest_id': move.location_dest_id.id,
                        'qty_done': remaining_qty,
                        'package_id': package.id,
                        'company_id': picking.company_id.id,
                    })

    def _check_import_lot_delivery_rules(self):
        """Validate Import Lot rules at outgoing picking validation time.

        Sale orders can be confirmed freely. If the delivery is linked to an Import Lot,
        the physical stock must exist inside the package named as that Import Lot.
        """
        Quant = self.env['stock.quant']
        for picking in self.filtered(lambda p: p.picking_type_code == 'outgoing'):
            sale = picking.sale_id
            if sale:
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

            if not picking.import_lot_id:
                continue

            package = self._get_or_create_import_lot_package(picking.import_lot_id, picking.company_id)
            errors = []
            for move in picking.move_ids_without_package.filtered(lambda m: m.product_id and m.product_id.detailed_type == 'product'):
                qty_to_deliver = self._get_move_qty_to_process(move)
                if not qty_to_deliver:
                    continue

                qty_in_move_uom = qty_to_deliver
                quants = Quant.search([
                    ('product_id', '=', move.product_id.id),
                    ('package_id', '=', package.id),
                    ('location_id.usage', '=', 'internal'),
                    ('company_id', 'in', [False, picking.company_id.id]),
                ])
                available_qty_product_uom = sum(quants.mapped('quantity'))
                available_qty = move.product_id.uom_id._compute_quantity(
                    available_qty_product_uom,
                    move.product_uom,
                    rounding_method='HALF-UP',
                )
                precision = move.product_uom.rounding or 0.01
                if float_compare(available_qty, qty_in_move_uom, precision_rounding=precision) < 0:
                    errors.append(_(
                        '- %(product)s: delivery quantity %(delivery_qty)s %(uom)s, available in package %(package)s: %(available)s %(uom)s.'
                    ) % {
                        'product': move.product_id.display_name,
                        'delivery_qty': qty_in_move_uom,
                        'available': available_qty,
                        'package': package.name,
                        'uom': move.product_uom.name,
                    })
            if errors:
                raise UserError(_(
                    'This delivery is linked to Import Lot %(lot)s, but some products do not have enough stock in package %(package)s.\n\n%(details)s'
                ) % {
                    'lot': picking.import_lot_id.name,
                    'package': package.name,
                    'details': '\n'.join(errors),
                })

    def _update_import_lot_after_receipt(self):
        for picking in self.filtered(lambda p: p.picking_type_code == 'incoming' and p.import_lot_id):
            lot = picking.import_lot_id
            if lot.state not in ('closed', 'cancelled'):
                if all(line.received_qty >= line.expected_qty for line in lot.line_ids):
                    lot.state = 'received'
                elif any(line.received_qty > 0 for line in lot.line_ids):
                    lot.state = 'partially_received'
