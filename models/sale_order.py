# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    import_lot_allocation_count = fields.Integer(
        string='Import Lot Allocations',
        compute='_compute_import_lot_allocation_count',
    )

    def _compute_import_lot_allocation_count(self):
        Allocation = self.env['import.lot.allocation']
        for order in self:
            order.import_lot_allocation_count = Allocation.search_count([('sale_order_id', '=', order.id)])

    def action_view_import_lot_allocations(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Import Lot Allocations'),
            'res_model': 'import.lot.allocation',
            'view_mode': 'tree,form',
            'domain': [('sale_order_id', '=', self.id)],
            'context': {'default_sale_order_id': self.id},
        }

    def action_confirm(self):
        res = super().action_confirm()
        for order in self:
            for line in order.order_line:
                if line.package_id:
                    line._sync_package_to_stock_moves()
        return res


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    package_id = fields.Many2one(
        'stock.quant.package',
        string='Package',
        copy=False,
        help='Physical package to use for this sale line. Deliveries will validate and consume stock from this package.',
    )
    package_available_qty = fields.Float(
        string='Available in Package',
        compute='_compute_package_available_qty',
        digits='Product Unit of Measure',
    )
    import_lot_allocation_ids = fields.One2many(
        'import.lot.allocation',
        'sale_line_id',
        string='Import Lot Allocations',
    )
    import_lot_allocated_qty = fields.Float(
        string='Import Lot Allocated Qty',
        compute='_compute_import_lot_allocation_qty',
        digits='Product Unit of Measure',
    )

    @api.depends('package_id', 'product_id', 'product_uom')
    def _compute_package_available_qty(self):
        Quant = self.env['stock.quant']
        for line in self:
            available = 0.0
            if line.package_id and line.product_id:
                quants = Quant.search([
                    ('product_id', '=', line.product_id.id),
                    ('package_id', '=', line.package_id.id),
                    ('location_id.usage', '=', 'internal'),
                    ('company_id', 'in', [False, line.company_id.id]),
                ])
                qty_product_uom = sum(quants.mapped('quantity'))
                available = line.product_id.uom_id._compute_quantity(
                    qty_product_uom,
                    line.product_uom or line.product_id.uom_id,
                    rounding_method='HALF-UP',
                )
            line.package_available_qty = available

    @api.depends('import_lot_allocation_ids.allocated_qty', 'import_lot_allocation_ids.state')
    def _compute_import_lot_allocation_qty(self):
        valid_states = ('reserved', 'received', 'assigned', 'done')
        for line in self:
            line.import_lot_allocated_qty = sum(
                line.import_lot_allocation_ids.filtered(lambda a: a.state in valid_states).mapped('allocated_qty')
            )

    def _sync_package_to_stock_moves(self):
        for line in self:
            moves = line.move_ids.filtered(lambda m: m.state not in ('done', 'cancel'))
            if moves:
                moves.write({'package_id': line.package_id.id if line.package_id else False})

    def write(self, vals):
        res = super().write(vals)
        if 'package_id' in vals:
            self._sync_package_to_stock_moves()
        return res

    def action_view_import_lot_allocations(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Import Lot Allocations'),
            'res_model': 'import.lot.allocation',
            'view_mode': 'tree,form',
            'domain': [('sale_line_id', '=', self.id)],
            'context': {'default_sale_line_id': self.id},
        }
