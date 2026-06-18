# -*- coding: utf-8 -*-
from odoo import fields, models, _


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    import_lot_ids = fields.One2many(
        'import.lot',
        'purchase_order_id',
        string='Import Lots',
    )
    import_lot_count = fields.Integer(
        string='Import Lot Count',
        compute='_compute_import_lot_count',
    )

    def _compute_import_lot_count(self):
        for order in self:
            order.import_lot_count = len(order.import_lot_ids)

    def action_create_import_lot(self):
        self.ensure_one()
        ImportLot = self.env['import.lot']
        lot_name = ImportLot._get_name_from_purchase_order(self)
        lot = ImportLot.create({
            'name': lot_name,
            'purchase_order_id': self.id,
            'partner_id': self.partner_id.id,
            'expected_date': self.date_planned,
            'company_id': self.company_id.id,
            'line_ids': [(0, 0, {
                'purchase_line_id': line.id,
                'product_id': line.product_id.id,
                'product_uom_id': line.product_uom.id,
                'expected_qty': line.product_qty,
            }) for line in self.order_line.filtered(lambda l: l.product_id and l.product_id.detailed_type == 'product')],
        })
        self.picking_ids.write({'import_lot_id': lot.id})
        return {
            'type': 'ir.actions.act_window',
            'name': _('Import Lot'),
            'res_model': 'import.lot',
            'view_mode': 'form',
            'res_id': lot.id,
        }

    def action_view_import_lots(self):
        self.ensure_one()
        action = {
            'type': 'ir.actions.act_window',
            'name': _('Import Lots'),
            'res_model': 'import.lot',
            'view_mode': 'tree,form',
            'domain': [('purchase_order_id', '=', self.id)],
            'context': {
                'default_purchase_order_id': self.id,
                'default_partner_id': self.partner_id.id,
                'default_company_id': self.company_id.id,
            },
        }
        if len(self.import_lot_ids) == 1:
            action.update({
                'view_mode': 'form',
                'res_id': self.import_lot_ids.id,
            })
        return action
