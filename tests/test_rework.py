# -*- coding: utf-8 -*-
from odoo.exceptions import UserError, ValidationError
from odoo.tests import common, tagged


@tagged('post_install', '-at_install')
class TestStockRework(common.TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create({
            'name': 'Rework Customer',
        })
        cls.product_a = cls.env['product.product'].create({
            'name': 'Lemon A',
            'type': 'product',
            'standard_price': 1.0,
        })
        cls.product_b = cls.env['product.product'].create({
            'name': 'Lemon B',
            'type': 'product',
            'list_price': 2.0,
            'standard_price': 1.5,
        })
        cls.stock_location = cls.env.ref('stock.stock_location_stock')
        cls.source_package = cls.env['stock.quant.package'].create({
            'name': '0001',
        })
        cls.env['stock.quant']._update_available_quantity(
            cls.product_a,
            cls.stock_location,
            10.0,
            package_id=cls.source_package,
        )

    def _create_sale_line(self, quantity=7.0):
        sale = self.env['sale.order'].create({
            'partner_id': self.customer.id,
        })
        line = self.env['sale.order.line'].create({
            'order_id': sale.id,
            'name': self.product_b.name,
            'product_id': self.product_b.id,
            'product_uom_qty': quantity,
            'product_uom': self.product_b.uom_id.id,
            'price_unit': self.product_b.list_price,
        })
        return sale, line

    def _create_rework(self, source_qty=7.0, destination_qty=7.0, sale_qty=7.0):
        sale, sale_line = self._create_sale_line(sale_qty)
        rework = self.env['stock.rework.order'].create({
            'source_package_id': self.source_package.id,
            'source_product_id': self.product_a.id,
            'source_location_id': self.stock_location.id,
            'source_qty': source_qty,
            'destination_product_id': self.product_b.id,
            'destination_location_id': self.stock_location.id,
            'destination_qty': destination_qty,
            'sale_order_id': sale.id,
            'sale_line_id': sale_line.id,
        })
        return rework, sale, sale_line

    def test_confirm_reserves_rework_output_without_purchase(self):
        rework, sale, sale_line = self._create_rework()

        rework.action_confirm()

        self.assertEqual(rework.state, 'confirmed')
        self.assertFalse(rework.import_lot_id.purchase_order_id)
        self.assertEqual(rework.import_lot_id.restricted_sale_order_id, sale)
        self.assertEqual(rework.import_lot_id.line_ids.product_id, self.product_b)
        self.assertEqual(rework.import_lot_id.line_ids.expected_qty, 7.0)
        self.assertEqual(sale_line.import_lot_id, rework.import_lot_id)
        self.assertEqual(sale_line.import_lot_allocation_ids.allocated_qty, 7.0)
        self.assertFalse(sale_line.planned_package_id.source_package_id)

    def test_process_consumes_a_and_produces_b_in_result_package(self):
        rework, _sale, sale_line = self._create_rework()

        rework.action_process()

        self.assertEqual(rework.state, 'done')
        self.assertEqual(rework.consume_move_id.state, 'done')
        self.assertEqual(rework.produce_move_id.state, 'done')
        self.assertEqual(rework.result_package_id.rework_order_id, rework)
        self.assertEqual(rework.import_lot_id.state, 'received')
        self.assertEqual(rework.import_lot_id.source_package_id, rework.result_package_id)
        self.assertEqual(rework.import_lot_id.line_ids.received_qty, 7.0)
        self.assertEqual(sale_line.planned_package_id.source_package_id, rework.result_package_id)

        source_a = self.env['stock.quant']._get_available_quantity(
            self.product_a,
            self.stock_location,
            package_id=self.source_package,
            strict=True,
        )
        result_b = self.env['stock.quant']._get_available_quantity(
            self.product_b,
            self.stock_location,
            package_id=rework.result_package_id,
            strict=True,
        )
        self.assertEqual(source_a, 3.0)
        self.assertEqual(result_b, 7.0)

    def test_rework_import_lot_is_restricted_to_selected_sale(self):
        rework, _sale, _sale_line = self._create_rework()
        rework.action_confirm()
        _other_sale, other_line = self._create_sale_line()

        with self.assertRaises(ValidationError), self.cr.savepoint():
            other_line.import_lot_id = rework.import_lot_id

    def test_delivery_waits_for_rework_physical_package(self):
        rework, sale, _sale_line = self._create_rework()
        rework.action_confirm()
        sale.action_confirm()
        picking = sale.picking_ids
        picking.move_ids.write({'quantity_done': 7.0})

        with self.assertRaises(UserError), self.cr.savepoint():
            picking.button_validate()

    def test_delivery_uses_rework_result_as_source_package(self):
        rework, sale, _sale_line = self._create_rework()
        rework.action_process()
        sale.action_confirm()
        picking = sale.picking_ids
        picking.move_ids.write({'quantity_done': 7.0})

        picking.with_context(skip_backorder=True).button_validate()

        self.assertEqual(
            picking.move_line_ids.package_id,
            rework.result_package_id,
        )
        self.assertEqual(
            picking.move_line_ids.result_package_id.planned_package_id.source_package_id,
            rework.result_package_id,
        )
        remaining_result_b = self.env['stock.quant']._get_available_quantity(
            self.product_b,
            self.stock_location,
            package_id=rework.result_package_id,
            strict=True,
        )
        self.assertEqual(remaining_result_b, 0.0)

    def test_not_enough_source_package_stock_is_rejected(self):
        rework, _sale, _sale_line = self._create_rework(source_qty=11.0)
        rework.action_confirm()

        with self.assertRaises(UserError), self.cr.savepoint():
            rework.action_process()

        self.assertEqual(rework.state, 'confirmed')
        self.assertFalse(rework.result_package_id)

    def test_result_must_cover_selected_sale_line(self):
        rework, _sale, _sale_line = self._create_rework(destination_qty=6.0, sale_qty=7.0)

        with self.assertRaises(UserError), self.cr.savepoint():
            rework.action_confirm()
