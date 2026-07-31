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
    expected_package_ids = fields.One2many(
        'stock.expected.package',
        'purchase_order_id',
        string='Future Packages',
    )
    expected_package_count = fields.Integer(
        string='Future Packages',
        compute='_compute_expected_package_count',
    )

    def _compute_import_lot_count(self):
        for order in self:
            order.import_lot_count = len(order.import_lot_ids)

    def _compute_expected_package_count(self):
        for order in self:
            order.expected_package_count = len(order.expected_package_ids)

    def action_create_import_lot(self):
        self.ensure_one()
        ImportLot = self.env['import.lot']
        expected_package = self.env[
            'stock.expected.package'
        ]._get_or_create_for_purchase(self)
        lot_name = ImportLot._get_name_from_purchase_order(self)
        lot = ImportLot.create({
            'name': lot_name,
            'purchase_order_id': self.id,
            'expected_package_id': expected_package.id,
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

    def action_view_expected_packages(self):
        self.ensure_one()
        expected_package = self.env[
            'stock.expected.package'
        ]._get_or_create_for_purchase(self)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Future Package'),
            'res_model': 'stock.expected.package',
            'view_mode': 'form',
            'res_id': expected_package.id,
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


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    created_from_transfer = fields.Boolean(
        string='Created from Transfer',
        copy=False,
        readonly=True,
        help='Technical flag for lines created after adding a product directly to a receipt.',
    )

    def _create_or_update_picking(self):
        if self.env.context.get('skip_order_to_transfer_sync'):
            return True
        return super()._create_or_update_picking()

    def unlink(self):
        self = self.with_context(skip_order_to_transfer_sync=True)
        return super().unlink()
