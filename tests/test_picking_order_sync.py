# -*- coding: utf-8 -*-
from odoo import fields
from odoo.tests import common, tagged


@tagged('post_install', '-at_install')
class TestPickingOrderSync(common.TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create({
            'name': 'Transfer Sync Customer',
        })
        cls.vendor = cls.env['res.partner'].create({
            'name': 'Transfer Sync Vendor',
            'supplier_rank': 1,
        })
        cls.original_product = cls.env['product.product'].create({
            'name': 'Original Transfer Product',
            'type': 'product',
            'list_price': 10.0,
            'standard_price': 4.0,
        })
        cls.added_product = cls.env['product.product'].create({
            'name': 'Added Transfer Product',
            'type': 'product',
            'list_price': 12.0,
            'standard_price': 5.0,
        })

    def _new_move_values(self, picking, product, quantity):
        return {
            'name': product.display_name,
            'product_id': product.id,
            'product_uom_qty': quantity,
            'product_uom': product.uom_id.id,
            'location_id': picking.location_id.id,
            'location_dest_id': picking.location_dest_id.id,
            'company_id': picking.company_id.id,
        }

    def test_added_delivery_product_creates_and_removes_sale_line(self):
        sale = self.env['sale.order'].create({
            'partner_id': self.customer.id,
        })
        original_line = self.env['sale.order.line'].create({
            'order_id': sale.id,
            'product_id': self.original_product.id,
            'product_uom_qty': 1.0,
            'product_uom': self.original_product.uom_id.id,
        })
        sale.action_confirm()
        picking = sale.picking_ids

        picking.write({
            'move_ids': [(0, 0, self._new_move_values(
                picking,
                self.added_product,
                3.0,
            ))],
        })

        added_move = picking.move_ids.filtered(
            lambda move: move.product_id == self.added_product
            and move.state != 'cancel'
        )
        added_line = sale.order_line.filtered(
            lambda line: line.product_id == self.added_product
        )
        self.assertEqual(len(added_move), 1)
        self.assertEqual(len(added_line), 1)
        self.assertTrue(added_line.created_from_transfer)
        self.assertEqual(added_line.product_uom_qty, 3.0)
        self.assertEqual(added_move.sale_line_id, added_line)

        picking.write({'move_ids': [(2, added_move.id, 0)]})

        self.assertTrue(original_line.exists())
        self.assertFalse(added_line.exists())

    def test_removing_original_delivery_product_removes_sale_line(self):
        sale = self.env['sale.order'].create({
            'partner_id': self.customer.id,
        })
        kept_line = self.env['sale.order.line'].create({
            'order_id': sale.id,
            'product_id': self.original_product.id,
            'product_uom_qty': 1.0,
            'product_uom': self.original_product.uom_id.id,
        })
        removed_line = self.env['sale.order.line'].create({
            'order_id': sale.id,
            'product_id': self.added_product.id,
            'product_uom_qty': 2.0,
            'product_uom': self.added_product.uom_id.id,
        })
        sale.action_confirm()
        picking = sale.picking_ids
        removed_move = picking.move_ids.filtered(
            lambda move: move.sale_line_id == removed_line
        )

        picking.write({'move_ids': [(2, removed_move.id, 0)]})

        self.assertTrue(kept_line.exists())
        self.assertFalse(removed_line.exists())

    def test_added_receipt_product_updates_purchase_and_import_lot(self):
        purchase = self.env['purchase.order'].create({
            'partner_id': self.vendor.id,
        })
        original_line = self.env['purchase.order.line'].create({
            'order_id': purchase.id,
            'product_id': self.original_product.id,
            'product_qty': 1.0,
            'product_uom': self.original_product.uom_id.id,
            'price_unit': self.original_product.standard_price,
            'date_planned': fields.Datetime.now(),
        })
        purchase.button_confirm()
        picking = purchase.picking_ids
        import_lot_action = purchase.action_create_import_lot()
        import_lot = self.env['import.lot'].browse(import_lot_action['res_id'])

        picking.write({
            'move_ids': [(0, 0, self._new_move_values(
                picking,
                self.added_product,
                4.0,
            ))],
        })

        added_move = picking.move_ids.filtered(
            lambda move: move.product_id == self.added_product
            and move.state != 'cancel'
        )
        added_line = purchase.order_line.filtered(
            lambda line: line.product_id == self.added_product
        )
        added_import_line = import_lot.line_ids.filtered(
            lambda line: line.product_id == self.added_product
        )
        self.assertEqual(len(added_move), 1)
        self.assertEqual(len(added_line), 1)
        self.assertTrue(added_line.created_from_transfer)
        self.assertEqual(added_line.product_qty, 4.0)
        self.assertEqual(added_move.purchase_line_id, added_line)
        self.assertEqual(added_import_line.purchase_line_id, added_line)
        self.assertEqual(added_import_line.expected_qty, 4.0)

        picking.write({'move_ids': [(2, added_move.id, 0)]})

        self.assertTrue(original_line.exists())
        self.assertFalse(added_line.exists())
        self.assertFalse(added_import_line.exists())

    def test_purchase_receipt_uses_po_number_as_package(self):
        purchase = self.env['purchase.order'].create({
            'partner_id': self.vendor.id,
        })
        self.env['purchase.order.line'].create({
            'order_id': purchase.id,
            'product_id': self.original_product.id,
            'product_qty': 2.0,
            'product_uom': self.original_product.uom_id.id,
            'price_unit': self.original_product.standard_price,
            'date_planned': fields.Datetime.now(),
        })
        purchase.button_confirm()
        action = purchase.action_create_import_lot()
        import_lot = self.env['import.lot'].browse(action['res_id'])
        expected = import_lot.expected_package_id

        self.assertEqual(expected.name, purchase.name)
        self.assertFalse(expected.physical_package_id)

        receipt = purchase.picking_ids
        receipt.move_ids.write({'quantity_done': 2.0})
        receipt.with_context(skip_backorder=True).button_validate()

        package = expected.physical_package_id
        self.assertTrue(package)
        self.assertEqual(package.name, purchase.name)
        self.assertEqual(import_lot.source_package_id, package)
        self.assertEqual(receipt.move_line_ids.result_package_id, package)
