# -*- coding: utf-8 -*-
from odoo.tests import common, tagged
from odoo.exceptions import ValidationError


@tagged('post_install', '-at_install')
class TestPlannedDeliveryPackages(common.TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create({
            'name': 'Planned Package Customer',
        })
        cls.product = cls.env['product.product'].create({
            'name': 'Planned Package Product',
            'type': 'product',
            'list_price': 10.0,
        })
        cls.stock_location = cls.env.ref('stock.stock_location_stock')
        cls.env['stock.quant']._update_available_quantity(
            cls.product,
            cls.stock_location,
            10.0,
        )

    def _create_sale_with_plan(self, quantity):
        sale = self.env['sale.order'].create({
            'partner_id': self.customer.id,
        })
        plan = self.env['stock.package.plan'].create({
            'name': 'PLAN-PARTIAL-DELIVERY',
            'sale_order_id': sale.id,
        })
        line = self.env['sale.order.line'].create({
            'order_id': sale.id,
            'name': self.product.name,
            'product_id': self.product.id,
            'product_uom_qty': quantity,
            'product_uom': self.product.uom_id.id,
            'price_unit': self.product.list_price,
            'planned_package_id': plan.id,
        })
        return sale, line, plan

    def test_partial_deliveries_create_distinct_physical_packages(self):
        sale, line, plan = self._create_sale_with_plan(10.0)
        sale.action_confirm()

        first_picking = sale.picking_ids
        self.assertEqual(len(first_picking), 1)
        self.assertEqual(first_picking.move_ids.planned_package_id, plan)
        self.assertEqual(plan.state, 'confirmed')
        self.assertFalse(plan.real_package_ids)

        first_picking.move_ids.write({'quantity_done': 4.0})
        first_picking.with_context(skip_backorder=True).button_validate()

        first_package = plan.real_package_ids
        self.assertEqual(len(first_package), 1)
        self.assertEqual(first_package.planned_picking_id, first_picking)
        self.assertEqual(first_picking.move_line_ids.result_package_id, first_package)

        backorder = sale.picking_ids.filtered(lambda picking: picking.state not in ('done', 'cancel'))
        self.assertEqual(len(backorder), 1)
        self.assertEqual(backorder.move_ids.planned_package_id, plan)
        self.assertEqual(plan.state, 'in_progress')

        backorder.move_ids.write({'quantity_done': 6.0})
        backorder.with_context(skip_backorder=True).button_validate()

        self.assertEqual(len(plan.real_package_ids), 2)
        self.assertNotEqual(
            first_package,
            backorder.move_line_ids.result_package_id,
            'The backorder must create a different physical package.',
        )
        self.assertEqual(backorder.move_line_ids.result_package_id.planned_picking_id, backorder)
        self.assertEqual(plan.state, 'done')
        self.assertEqual(line.qty_delivered, 10.0)

    def test_plan_from_another_sale_order_is_rejected(self):
        sale, line, _plan = self._create_sale_with_plan(1.0)
        other_sale = self.env['sale.order'].create({
            'partner_id': self.customer.id,
        })
        other_plan = self.env['stock.package.plan'].create({
            'name': 'PLAN-OTHER-SALE',
            'sale_order_id': other_sale.id,
        })

        with self.assertRaises(ValidationError):
            line.planned_package_id = other_plan
