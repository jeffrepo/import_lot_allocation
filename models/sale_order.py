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


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

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

    @api.depends('import_lot_allocation_ids.allocated_qty', 'import_lot_allocation_ids.state')
    def _compute_import_lot_allocation_qty(self):
        valid_states = ('reserved', 'received', 'assigned', 'done')
        for line in self:
            line.import_lot_allocated_qty = sum(
                line.import_lot_allocation_ids.filtered(lambda a: a.state in valid_states).mapped('allocated_qty')
            )

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
