# -*- coding: utf-8 -*-
from odoo import fields, models, _
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare


class StockMove(models.Model):
    _inherit = 'stock.move'

    package_id = fields.Many2one(
        'stock.quant.package',
        string='Package',
        copy=False,
        help='Physical package selected from the sale order line. Outgoing move lines will consume from this package.',
    )


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
        # For outgoing deliveries, consume package per stock move / sale order line.
        self._assign_sale_line_packages_on_delivery()
        self._check_package_delivery_rules()
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
        """Use the Import Lot reference as the physical package on receipts."""
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

    def _assign_sale_line_packages_on_delivery(self):
        """Use the package selected on each sale line / stock move for delivery move lines."""
        MoveLine = self.env['stock.move.line']
        for picking in self.filtered(lambda p: p.picking_type_code == 'outgoing'):
            for move in picking.move_ids_without_package.filtered(lambda m: m.product_id and m.product_id.detailed_type == 'product' and m.package_id):
                package = move.package_id
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

    def _check_package_delivery_rules(self):
        """Validate package stock at outgoing picking validation time.

        Sale orders can be confirmed freely. If a sale line / stock move has a selected
        package, the physical stock must exist inside that package. This replaces the
        previous picking-level Import Lot validation, allowing one delivery to contain
        products from different packages.
        """
        Quant = self.env['stock.quant']
        for picking in self.filtered(lambda p: p.picking_type_code == 'outgoing'):
            errors = []
            for move in picking.move_ids_without_package.filtered(lambda m: m.product_id and m.product_id.detailed_type == 'product' and m.package_id):
                qty_to_deliver = self._get_move_qty_to_process(move)
                if not qty_to_deliver:
                    continue

                quants = Quant.search([
                    ('product_id', '=', move.product_id.id),
                    ('package_id', '=', move.package_id.id),
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
                if float_compare(available_qty, qty_to_deliver, precision_rounding=precision) < 0:
                    errors.append(_(
                        '- %(product)s: delivery quantity %(delivery_qty)s %(uom)s, available in package %(package)s: %(available)s %(uom)s.'
                    ) % {
                        'product': move.product_id.display_name,
                        'delivery_qty': qty_to_deliver,
                        'available': available_qty,
                        'package': move.package_id.name,
                        'uom': move.product_uom.name,
                    })
            if errors:
                raise UserError(_(
                    'Some products do not have enough stock in the selected packages.\n\n%(details)s'
                ) % {
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
