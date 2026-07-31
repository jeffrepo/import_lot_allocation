# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class StockExpectedPackage(models.Model):
    _name = 'stock.expected.package'
    _description = 'Expected Purchase Package'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(
        string='Future Package Number',
        required=True,
        copy=False,
        index=True,
        tracking=True,
        help='Reserved package number. For purchases it is exactly the Purchase Order number.',
    )
    purchase_order_id = fields.Many2one(
        'purchase.order',
        string='Purchase Order',
        required=True,
        ondelete='restrict',
        check_company=True,
        copy=False,
        index=True,
        tracking=True,
    )
    import_lot_ids = fields.One2many(
        'import.lot',
        'expected_package_id',
        string='Import Lots',
        readonly=True,
    )
    physical_package_id = fields.Many2one(
        'stock.quant.package',
        string='Physical Package',
        ondelete='restrict',
        check_company=True,
        copy=False,
        readonly=True,
        index=True,
        tracking=True,
        help='Empty package created when a Rework is confirmed and filled by the Purchase receipt.',
    )
    expected_location_id = fields.Many2one(
        'stock.location',
        string='Expected Stock Location',
        required=True,
        ondelete='restrict',
        check_company=True,
        tracking=True,
        domain="[('usage', '=', 'internal'), '|', ('company_id', '=', False), ('company_id', '=', company_id)]",
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    state = fields.Selection([
        ('expected', 'Expected'),
        ('created', 'Physical Package Created'),
        ('received', 'Received'),
    ], string='Status', compute='_compute_state', store=True)

    _sql_constraints = [
        (
            'purchase_order_company_uniq',
            'unique(purchase_order_id, company_id)',
            'A Purchase Order can only have one future package number.',
        ),
        (
            'physical_package_uniq',
            'unique(physical_package_id)',
            'A physical package can only be linked to one future package number.',
        ),
    ]

    @api.constrains('name', 'purchase_order_id', 'company_id')
    def _check_purchase_reference(self):
        for expected in self:
            if expected.company_id != expected.purchase_order_id.company_id:
                raise ValidationError(_(
                    'The future package and Purchase Order must belong to the same company.'
                ))
            if expected.name != expected.purchase_order_id.name:
                raise ValidationError(_(
                    'The future package number must be exactly the Purchase Order number: %s.'
                ) % expected.purchase_order_id.name)

    @api.depends(
        'physical_package_id',
        'physical_package_id.quant_ids.quantity',
        'physical_package_id.quant_ids.location_id.usage',
    )
    def _compute_state(self):
        for expected in self:
            internal_stock = expected.physical_package_id.quant_ids.filtered(
                lambda quant: quant.location_id.usage == 'internal' and quant.quantity > 0
            )
            if internal_stock:
                expected.state = 'received'
            elif expected.physical_package_id:
                expected.state = 'created'
            else:
                expected.state = 'expected'

    @api.model
    def _get_purchase_destination_location(self, purchase_order):
        purchase_order.ensure_one()
        pickings = purchase_order.picking_ids.filtered(
            lambda picking: picking.state != 'cancel' and picking.picking_type_code == 'incoming'
        ).sorted('id')
        if pickings:
            return pickings[0].location_dest_id
        return purchase_order.picking_type_id.default_location_dest_id

    @api.model
    def _get_or_create_for_purchase(self, purchase_order):
        purchase_order.ensure_one()
        expected = self.search([
            ('purchase_order_id', '=', purchase_order.id),
            ('company_id', '=', purchase_order.company_id.id),
        ], limit=1)
        destination = self._get_purchase_destination_location(purchase_order)
        if not destination:
            raise ValidationError(_(
                'Purchase Order %s does not have a destination stock location.'
            ) % purchase_order.name)

        values = {
            'name': purchase_order.name,
            'expected_location_id': destination.id,
        }
        if expected:
            if expected.name != purchase_order.name or expected.expected_location_id != destination:
                expected.write(values)
            return expected

        values.update({
            'purchase_order_id': purchase_order.id,
            'company_id': purchase_order.company_id.id,
        })
        return self.create(values)

    @api.model
    def _get_or_create_for_physical_package(self, package, purchase_order=False):
        """Create a reference for a legacy physical package when needed."""
        package.ensure_one()
        expected = self.search([('physical_package_id', '=', package.id)], limit=1)
        if expected:
            return expected
        if not purchase_order:
            return self
        expected = self._get_or_create_for_purchase(purchase_order)
        if not expected.physical_package_id:
            expected.physical_package_id = package.id
            package.expected_package_id = expected.id
        return expected

    def _get_or_create_physical_package(self):
        self.ensure_one()
        if self.physical_package_id:
            if self.physical_package_id.name != self.name:
                self.physical_package_id.name = self.name
            return self.physical_package_id

        Package = self.env['stock.quant.package']
        receipt_packages = self.import_lot_ids.mapped(
            'picking_ids.move_line_ids.result_package_id'
        ).filtered(
            lambda package: not package.expected_package_id
            or package.expected_package_id == self
        )
        source_packages = self.import_lot_ids.mapped('source_package_id').filtered(
            lambda package: not package.expected_package_id
            or package.expected_package_id == self
        )
        candidates = receipt_packages | source_packages
        package = candidates if len(candidates) == 1 else Package
        if not package:
            package = Package.search([
                ('name', '=', self.name),
                ('expected_package_id', '=', False),
                '|',
                ('company_id', '=', False),
                ('company_id', '=', self.company_id.id),
            ], limit=1)
        if not package:
            package = Package.create({
                'name': self.name,
                'company_id': self.company_id.id,
                'expected_package_id': self.id,
            })
        elif package.name != self.name or package.expected_package_id != self:
            package.write({
                'name': self.name,
                'expected_package_id': self.id,
            })

        self.physical_package_id = package.id
        self.import_lot_ids.write({'source_package_id': package.id})
        plans = self.env['stock.package.plan'].search([
            ('import_lot_id', 'in', self.import_lot_ids.ids),
        ])
        plans.write({'source_package_id': package.id})
        return package

    def action_create_physical_package(self):
        for expected in self:
            expected._get_or_create_physical_package()
        return True

    def action_view_physical_package(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Physical Package'),
            'res_model': 'stock.quant.package',
            'view_mode': 'form',
            'res_id': self.physical_package_id.id,
        }


class StockQuantPackage(models.Model):
    _inherit = 'stock.quant.package'

    expected_package_id = fields.Many2one(
        'stock.expected.package',
        string='Future Package Reference',
        ondelete='restrict',
        copy=False,
        readonly=True,
        index=True,
    )
