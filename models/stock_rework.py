# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare


ACTIVE_ALLOCATION_STATES = ('reserved', 'received', 'assigned', 'done')


class StockReworkOrder(models.Model):
    _name = 'stock.rework.order'
    _description = 'Stock Rework Order'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(
        string='Reference',
        required=True,
        copy=False,
        index=True,
        tracking=True,
        default=lambda self: self.env['ir.sequence'].next_by_code('stock.rework.order') or _('New'),
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    sale_order_id = fields.Many2one(
        'sale.order',
        string='Reserved for Sale Order',
        required=True,
        check_company=True,
        tracking=True,
        domain="[('company_id', '=', company_id), ('state', 'not in', ('done', 'cancel'))]",
    )
    line_ids = fields.One2many(
        'stock.rework.line',
        'rework_order_id',
        string='Conversions',
        copy=True,
    )
    line_count = fields.Integer(string='Conversions', compute='_compute_links')
    output_import_lot_ids = fields.Many2many(
        'import.lot',
        string='Rework Import Lots',
        compute='_compute_links',
    )
    output_import_lot_count = fields.Integer(string='Rework Import Lots', compute='_compute_links')
    result_package_ids = fields.Many2many(
        'stock.quant.package',
        string='Reworked Packages',
        compute='_compute_links',
    )
    result_package_count = fields.Integer(string='Reworked Packages', compute='_compute_links')
    stock_move_ids = fields.Many2many(
        'stock.move',
        string='Stock Moves',
        compute='_compute_links',
    )
    stock_move_count = fields.Integer(string='Stock Moves', compute='_compute_links')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('done', 'Done'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, copy=False, tracking=True, index=True)
    note = fields.Text(string='Notes')

    # Legacy single-conversion columns are intentionally preserved so databases
    # upgraded from 16.0.5 keep their history. New records use ``line_ids``.
    source_package_id = fields.Many2one(
        'stock.quant.package',
        string='Legacy Source Package',
        check_company=True,
        tracking=True,
    )
    source_product_domain_ids = fields.Many2many(
        'product.product',
        string='Legacy Products in Source Package',
        compute='_compute_legacy_source_product_domain_ids',
    )
    source_product_id = fields.Many2one(
        'product.product',
        string='Legacy Source Product',
        tracking=True,
    )
    source_uom_id = fields.Many2one(
        'uom.uom',
        string='Legacy Source UoM',
        related='source_product_id.uom_id',
        readonly=True,
    )
    source_location_id = fields.Many2one(
        'stock.location',
        string='Legacy Source Location',
        check_company=True,
        tracking=True,
    )
    source_available_qty = fields.Float(
        string='Legacy Available Quantity',
        compute='_compute_legacy_source_available_qty',
        digits='Product Unit of Measure',
    )
    source_qty = fields.Float(
        string='Legacy Quantity to Consume',
        digits='Product Unit of Measure',
        tracking=True,
    )
    destination_product_id = fields.Many2one(
        'product.product',
        string='Legacy Result Product',
        tracking=True,
    )
    destination_uom_id = fields.Many2one(
        'uom.uom',
        string='Legacy Result UoM',
        related='destination_product_id.uom_id',
        readonly=True,
    )
    destination_location_id = fields.Many2one(
        'stock.location',
        string='Legacy Result Location',
        check_company=True,
        tracking=True,
    )
    destination_qty = fields.Float(
        string='Legacy Quantity to Produce',
        digits='Product Unit of Measure',
        tracking=True,
    )
    sale_line_id = fields.Many2one(
        'sale.order.line',
        string='Legacy Sale Order Line',
        tracking=True,
    )
    import_lot_id = fields.Many2one(
        'import.lot',
        string='Legacy Rework Import Lot',
        copy=False,
        readonly=True,
        ondelete='restrict',
        index=True,
    )
    result_package_id = fields.Many2one(
        'stock.quant.package',
        string='Legacy Reworked Package',
        copy=False,
        readonly=True,
        ondelete='restrict',
        index=True,
    )
    consume_move_id = fields.Many2one(
        'stock.move',
        string='Legacy Consumption Move',
        copy=False,
        readonly=True,
        ondelete='restrict',
    )
    produce_move_id = fields.Many2one(
        'stock.move',
        string='Legacy Production Move',
        copy=False,
        readonly=True,
        ondelete='restrict',
    )
    legacy_data_pending = fields.Boolean(compute='_compute_legacy_data_pending')

    _sql_constraints = [
        (
            'name_company_uniq',
            'unique(name, company_id)',
            'The Rework reference must be unique per company.',
        ),
        (
            'import_lot_uniq',
            'unique(import_lot_id)',
            'A legacy Import Lot can only belong to one Rework Order.',
        ),
    ]

    @api.depends(
        'line_ids',
        'line_ids.output_import_lot_id',
        'line_ids.result_package_id',
        'line_ids.consume_move_id',
        'line_ids.produce_move_id',
        'import_lot_id',
        'result_package_id',
        'consume_move_id',
        'produce_move_id',
    )
    def _compute_links(self):
        for rework in self:
            import_lots = rework.line_ids.mapped('output_import_lot_id') | rework.import_lot_id
            packages = rework.line_ids.mapped('result_package_id') | rework.result_package_id
            moves = (
                rework.line_ids.mapped('consume_move_id')
                | rework.line_ids.mapped('produce_move_id')
                | rework.consume_move_id
                | rework.produce_move_id
            )
            rework.line_count = len(rework.line_ids)
            rework.output_import_lot_ids = import_lots
            rework.output_import_lot_count = len(import_lots)
            rework.result_package_ids = packages
            rework.result_package_count = len(packages)
            rework.stock_move_ids = moves
            rework.stock_move_count = len(moves)

    @api.depends('line_ids', 'source_package_id', 'source_product_id', 'destination_product_id')
    def _compute_legacy_data_pending(self):
        for rework in self:
            rework.legacy_data_pending = bool(
                not rework.line_ids
                and rework.source_package_id
                and rework.source_product_id
                and rework.destination_product_id
            )

    @api.depends('source_package_id')
    def _compute_legacy_source_product_domain_ids(self):
        for rework in self:
            quants = rework.source_package_id.quant_ids.filtered(
                lambda quant: quant.location_id.usage == 'internal' and quant.quantity > 0
            )
            rework.source_product_domain_ids = quants.mapped('product_id')

    @api.depends('source_package_id', 'source_product_id', 'source_location_id')
    def _compute_legacy_source_available_qty(self):
        Quant = self.env['stock.quant']
        for rework in self:
            available = 0.0
            if rework.source_package_id and rework.source_product_id and rework.source_location_id:
                available = Quant._get_available_quantity(
                    rework.source_product_id,
                    rework.source_location_id,
                    package_id=rework.source_package_id,
                    strict=True,
                )
            rework.source_available_qty = available

    @api.model_create_multi
    def create(self, vals_list):
        Package = self.env['stock.quant.package']
        for vals in vals_list:
            if vals.get('source_package_id'):
                package_location = Package.browse(vals['source_package_id']).location_id
                if package_location:
                    vals['source_location_id'] = package_location.id
                    vals['destination_location_id'] = package_location.id
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('source_package_id'):
            vals = dict(vals)
            package_location = self.env['stock.quant.package'].browse(
                vals['source_package_id']
            ).location_id
            if package_location:
                vals['source_location_id'] = package_location.id
                vals['destination_location_id'] = package_location.id
        return super().write(vals)

    @api.constrains('sale_order_id', 'state')
    def _check_one_active_rework_per_sale(self):
        for rework in self.filtered(lambda record: record.state != 'cancelled'):
            duplicate = self.search([
                ('id', '!=', rework.id),
                ('sale_order_id', '=', rework.sale_order_id.id),
                ('state', '!=', 'cancelled'),
            ], limit=1)
            if duplicate:
                raise ValidationError(_(
                    'Sale Order %(sale)s already has active Rework %(rework)s. '
                    'Add the conversions to that Rework instead.'
                ) % {
                    'sale': rework.sale_order_id.name,
                    'rework': duplicate.name,
                })

    @api.constrains('source_qty', 'destination_qty')
    def _check_legacy_positive_quantities(self):
        for rework in self.filtered(lambda record: not record.line_ids and record.source_product_id):
            if rework.source_qty <= 0 or rework.destination_qty <= 0:
                raise ValidationError(_('Rework quantities must be greater than zero.'))

    @api.constrains('source_product_id', 'destination_product_id')
    def _check_legacy_different_products(self):
        for rework in self.filtered(lambda record: not record.line_ids):
            if rework.source_product_id and rework.source_product_id == rework.destination_product_id:
                raise ValidationError(_('The source product and result product must be different.'))

    @api.constrains('source_location_id', 'destination_location_id')
    def _check_legacy_same_package_location(self):
        for rework in self.filtered(lambda record: not record.line_ids):
            if (
                rework.source_location_id
                and rework.destination_location_id
                and rework.source_location_id != rework.destination_location_id
            ):
                raise ValidationError(_(
                    'The result location must match the source location because Rework keeps '
                    'both products in the same physical package.'
                ))

    @api.constrains('sale_order_id', 'sale_line_id', 'destination_product_id')
    def _check_legacy_sale_line(self):
        for rework in self.filtered(lambda record: not record.line_ids and record.sale_line_id):
            if rework.sale_line_id.order_id != rework.sale_order_id:
                raise ValidationError(_('The Sale Order line must belong to the Rework Sale Order.'))
            if rework.sale_line_id.product_id != rework.destination_product_id:
                raise ValidationError(_('The Sale Order line product must be the Rework result product.'))

    def _ensure_line_records(self):
        """Turn a pre-16.0.6 single conversion into one Rework line lazily."""
        Line = self.env['stock.rework.line']
        for rework in self.filtered(lambda record: not record.line_ids):
            if not (
                rework.source_package_id
                and rework.source_product_id
                and rework.destination_product_id
                and rework.sale_line_id
            ):
                continue
            source_lot = self.env['import.lot'].search([
                ('source_package_id', '=', rework.source_package_id.id),
                ('purchase_order_id', '!=', False),
            ], limit=1)
            output_line = rework.import_lot_id.line_ids.filtered(
                lambda line: line.product_id == rework.destination_product_id
            )[:1]
            allocation = rework.import_lot_id.allocation_ids.filtered(
                lambda record: record.sale_line_id == rework.sale_line_id
            )[:1]
            values = {
                'rework_order_id': rework.id,
                'source_import_lot_id': source_lot.id or False,
                'source_package_id': rework.source_package_id.id,
                'source_product_id': rework.source_product_id.id,
                'source_location_id': rework.source_location_id.id,
                'source_qty': rework.source_qty,
                'destination_product_id': rework.destination_product_id.id,
                'destination_location_id': rework.destination_location_id.id,
                'destination_qty': rework.destination_qty,
                'sale_line_id': rework.sale_line_id.id,
                'output_import_lot_id': rework.import_lot_id.id or False,
                'output_import_lot_line_id': output_line.id or False,
                'allocation_id': allocation.id or False,
                'result_package_id': rework.result_package_id.id or False,
                'consume_move_id': rework.consume_move_id.id or False,
                'produce_move_id': rework.produce_move_id.id or False,
            }
            Line.with_context(allow_rework_line_update=True).create(values)
        return self.mapped('line_ids')

    def _check_can_confirm(self):
        for rework in self:
            rework._ensure_line_records()
            if not rework.line_ids:
                raise UserError(_('Add at least one conversion line before confirming the Rework.'))
            if rework.sale_order_id.state in ('done', 'cancel'):
                raise UserError(_('The selected Sale Order is done or cancelled.'))
            rework.line_ids._check_configuration()
            rework._check_sale_capacity()

    def _check_sale_capacity(self):
        self.ensure_one()
        output_lots = self.line_ids.mapped('output_import_lot_id')
        for sale_line in self.line_ids.mapped('sale_line_id'):
            lines = self.line_ids.filtered(lambda line: line.sale_line_id == sale_line)
            active_allocations = sale_line.import_lot_allocation_ids.filtered(
                lambda allocation: allocation.state in ACTIVE_ALLOCATION_STATES
                and allocation.import_lot_id not in output_lots
            )
            allocated_sale_qty = sum(
                allocation.product_uom_id._compute_quantity(
                    allocation.allocated_qty,
                    sale_line.product_uom,
                    round=False,
                )
                for allocation in active_allocations
            )
            requested_sale_qty = sum(
                line.destination_uom_id._compute_quantity(
                    line.destination_qty,
                    sale_line.product_uom,
                    round=False,
                )
                for line in lines
            )
            available_sale_qty = max(sale_line.product_uom_qty - allocated_sale_qty, 0.0)
            if float_compare(
                requested_sale_qty,
                available_sale_qty,
                precision_rounding=sale_line.product_uom.rounding or 0.01,
            ) > 0:
                raise UserError(_(
                    'The Rework lines require %(requested)s %(uom)s on Sale Order line '
                    '%(line)s, but only %(available)s %(uom)s remain without another allocation.'
                ) % {
                    'requested': requested_sale_qty,
                    'available': available_sale_qty,
                    'uom': sale_line.product_uom.name,
                    'line': sale_line.display_name,
                })

    def _sync_partial_plan_to_sale_moves(self):
        for rework in self:
            rework._ensure_line_records()
            rework.line_ids._sync_partial_plan_to_sale_moves()

    def _sync_legacy_single_line_links(self):
        """Keep integrations that read the old header fields working for one-line Reworks."""
        for rework in self.filtered(lambda record: len(record.line_ids) == 1):
            line = rework.line_ids
            rework.write({
                'import_lot_id': line.output_import_lot_id.id or False,
                'result_package_id': line.result_package_id.id or False,
                'consume_move_id': line.consume_move_id.id or False,
                'produce_move_id': line.produce_move_id.id or False,
            })

    def action_confirm(self):
        for rework in self:
            if rework.state != 'draft':
                continue
            rework._check_can_confirm()
            for line in rework.line_ids.sorted(lambda record: (record.sequence, record.id)):
                line._prepare_physical_source_package()
                output_lot = line.output_import_lot_id or line._create_output_import_lot()
                line._create_output_allocation(output_lot)
            rework._sync_legacy_single_line_links()
            rework.state = 'confirmed'
            rework._sync_partial_plan_to_sale_moves()
        return True

    def action_process(self):
        for rework in self:
            if rework.state == 'draft':
                rework.action_confirm()
            if rework.state != 'confirmed':
                continue

            rework._check_can_confirm()
            rework.line_ids._check_source_availability()
            for line in rework.line_ids.sorted(lambda record: (record.sequence, record.id)):
                line._process_conversion()
            rework._sync_legacy_single_line_links()
            rework.state = 'done'
        return True

    def action_cancel(self):
        for rework in self:
            if rework.state == 'done':
                raise UserError(_(
                    'A completed Rework cannot be cancelled because stock has already moved. '
                    'Create a reverse Rework if you need to undo it.'
                ))
            rework._ensure_line_records()
            output_lots = rework.line_ids.mapped('output_import_lot_id') | rework.import_lot_id
            for output_lot in output_lots:
                plans = self.env['stock.package.plan'].search([
                    ('import_lot_id', '=', output_lot.id),
                ])
                open_plan_moves = plans.mapped('move_ids').filtered(
                    lambda move: move.state not in ('done', 'cancel')
                )
                if open_plan_moves:
                    open_plan_moves._do_unreserve()
                    open_plan_moves.write({'planned_package_id': False})
                    open_plan_moves._action_assign()
                output_lot.allocation_ids.filtered(
                    lambda allocation: allocation.state not in ('done', 'cancelled')
                ).write({'state': 'cancelled'})
                plans.exists()._unlink_if_unused_automatic()
                output_lot.state = 'cancelled'
            rework.state = 'cancelled'
        return True

    def _open_related_records(self, name, model, records):
        self.ensure_one()
        action = {
            'type': 'ir.actions.act_window',
            'name': name,
            'res_model': model,
            'view_mode': 'tree,form',
            'domain': [('id', 'in', records.ids)],
        }
        if len(records) == 1:
            action.update({'view_mode': 'form', 'res_id': records.id})
        return action

    def action_view_import_lots(self):
        self.ensure_one()
        return self._open_related_records(
            _('Rework Import Lots'),
            'import.lot',
            self.output_import_lot_ids,
        )

    def action_view_result_packages(self):
        self.ensure_one()
        return self._open_related_records(
            _('Reworked Packages'),
            'stock.quant.package',
            self.result_package_ids,
        )

    def action_view_moves(self):
        self.ensure_one()
        return self._open_related_records(
            _('Rework Stock Moves'),
            'stock.move',
            self.stock_move_ids,
        )

    # Backward-compatible object actions referenced by pre-upgrade bookmarks/views.
    def action_view_import_lot(self):
        return self.action_view_import_lots()

    def action_view_result_package(self):
        return self.action_view_result_packages()

    def unlink(self):
        if self.filtered(lambda rework: rework.state not in ('draft', 'cancelled')):
            raise UserError(_('Only draft or cancelled Rework Orders can be deleted.'))
        return super().unlink()


class StockReworkLine(models.Model):
    _name = 'stock.rework.line'
    _description = 'Stock Rework Conversion Line'
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)
    rework_order_id = fields.Many2one(
        'stock.rework.order',
        string='Rework Order',
        required=True,
        ondelete='cascade',
        index=True,
    )
    company_id = fields.Many2one(
        related='rework_order_id.company_id',
        store=True,
        index=True,
    )
    sale_order_id = fields.Many2one(
        related='rework_order_id.sale_order_id',
        store=True,
        index=True,
    )
    state = fields.Selection(related='rework_order_id.state', store=True)
    source_import_lot_id = fields.Many2one(
        'import.lot',
        string='Source PO / Future Package',
        ondelete='restrict',
        check_company=True,
        index=True,
        domain="[('company_id', '=', company_id), ('purchase_order_id', '!=', False), ('state', '!=', 'cancelled')]",
        help='Select the purchased Import Lot even while it is still in transit.',
    )
    source_expected_package_id = fields.Many2one(
        'stock.expected.package',
        string='Future Package Number',
        related='source_import_lot_id.expected_package_id',
        store=True,
        readonly=True,
    )
    source_package_id = fields.Many2one(
        'stock.quant.package',
        string='Physical Source Package',
        ondelete='restrict',
        check_company=True,
        copy=False,
        index=True,
        domain="[('location_id.usage', '=', 'internal'), '|', ('company_id', '=', False), ('company_id', '=', company_id)]",
        help='Created with the PO number when the Rework is confirmed; stock arrives here on receipt.',
    )
    source_product_domain_ids = fields.Many2many(
        'product.product',
        string='Available Source Products',
        compute='_compute_source_product_domain_ids',
    )
    source_product_id = fields.Many2one(
        'product.product',
        string='Source Product',
        required=True,
        domain="[('id', 'in', source_product_domain_ids)]",
    )
    source_uom_id = fields.Many2one(
        'uom.uom',
        string='Source UoM',
        related='source_product_id.uom_id',
        readonly=True,
    )
    source_location_id = fields.Many2one(
        'stock.location',
        string='Source Location',
        check_company=True,
        domain="[('usage', '=', 'internal'), '|', ('company_id', '=', False), ('company_id', '=', company_id)]",
    )
    source_available_qty = fields.Float(
        string='Available in Package',
        compute='_compute_source_available_qty',
        digits='Product Unit of Measure',
    )
    source_qty = fields.Float(
        string='Quantity to Consume',
        required=True,
        default=1.0,
        digits='Product Unit of Measure',
    )
    destination_product_id = fields.Many2one(
        'product.product',
        string='Result Product',
        required=True,
        domain="[('detailed_type', '=', 'product')]",
    )
    destination_uom_id = fields.Many2one(
        'uom.uom',
        string='Result UoM',
        related='destination_product_id.uom_id',
        readonly=True,
    )
    destination_location_id = fields.Many2one(
        'stock.location',
        string='Result Location',
        check_company=True,
        domain="[('usage', '=', 'internal'), '|', ('company_id', '=', False), ('company_id', '=', company_id)]",
    )
    destination_qty = fields.Float(
        string='Quantity to Produce',
        required=True,
        default=1.0,
        digits='Product Unit of Measure',
    )
    sale_line_id = fields.Many2one(
        'sale.order.line',
        string='Sale Order Line',
        required=True,
        ondelete='restrict',
        domain=(
            "[('order_id', '=', sale_order_id), ('product_id', '=', destination_product_id), "
            "('display_type', '=', False)]"
        ),
        help='The result quantity is allocated without splitting the commercial Sale Order line.',
    )
    output_import_lot_id = fields.Many2one(
        'import.lot',
        string='Result Import Lot',
        copy=False,
        readonly=True,
        ondelete='restrict',
        index=True,
    )
    output_import_lot_line_id = fields.Many2one(
        'import.lot.line',
        string='Result Import Lot Line',
        copy=False,
        readonly=True,
        ondelete='restrict',
    )
    allocation_id = fields.Many2one(
        'import.lot.allocation',
        string='Sale Allocation',
        copy=False,
        readonly=True,
        ondelete='restrict',
    )
    result_package_id = fields.Many2one(
        'stock.quant.package',
        string='Reworked Package',
        copy=False,
        readonly=True,
        ondelete='restrict',
        index=True,
    )
    consume_move_id = fields.Many2one(
        'stock.move',
        string='Consumption Move',
        copy=False,
        readonly=True,
        ondelete='restrict',
    )
    produce_move_id = fields.Many2one(
        'stock.move',
        string='Production Move',
        copy=False,
        readonly=True,
        ondelete='restrict',
    )
    note = fields.Char(string='Instructions')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._prepare_source_values(vals)
        return super().create(vals_list)

    def write(self, vals):
        vals = dict(vals)
        if 'source_import_lot_id' in vals or 'source_package_id' in vals:
            self._prepare_source_values(vals)
        return super().write(vals)

    @api.model
    def _prepare_source_values(self, vals):
        source_lot = self.env['import.lot'].browse(vals.get('source_import_lot_id')).exists()
        package = self.env['stock.quant.package'].browse(vals.get('source_package_id')).exists()
        location = self.env['stock.location']
        if source_lot:
            expected = source_lot._ensure_expected_package()
            package = expected.physical_package_id
            location = package.location_id or expected.expected_location_id
            vals['source_package_id'] = package.id or False
        elif package:
            location = package.location_id
        if location:
            vals['source_location_id'] = location.id
            vals['destination_location_id'] = location.id

    @api.depends(
        'source_import_lot_id.line_ids.product_id',
        'source_package_id.quant_ids.product_id',
        'source_package_id.quant_ids.quantity',
    )
    def _compute_source_product_domain_ids(self):
        for line in self:
            expected_products = line.source_import_lot_id.line_ids.mapped('product_id')
            received_products = line.source_package_id.quant_ids.filtered(
                lambda quant: quant.location_id.usage == 'internal' and quant.quantity > 0
            ).mapped('product_id')
            line.source_product_domain_ids = expected_products | received_products

    @api.depends('source_package_id', 'source_product_id', 'source_location_id')
    def _compute_source_available_qty(self):
        Quant = self.env['stock.quant']
        for line in self:
            available = 0.0
            if line.source_package_id and line.source_product_id and line.source_location_id:
                available = Quant._get_available_quantity(
                    line.source_product_id,
                    line.source_location_id,
                    package_id=line.source_package_id,
                    strict=True,
                )
            line.source_available_qty = available

    @api.onchange('source_import_lot_id')
    def _onchange_source_import_lot_id(self):
        for line in self:
            expected = line.source_import_lot_id.expected_package_id
            line.source_package_id = expected.physical_package_id
            location = (
                expected.physical_package_id.location_id
                or expected.expected_location_id
            )
            line.source_location_id = location
            line.destination_location_id = location
            products = line.source_import_lot_id.line_ids.mapped('product_id')
            line.source_product_id = products if len(products) == 1 else False

    @api.onchange('source_package_id')
    def _onchange_source_package_id(self):
        for line in self:
            location = line.source_package_id.location_id
            if location:
                line.source_location_id = location
                line.destination_location_id = location
            if not line.source_import_lot_id:
                products = line.source_package_id.quant_ids.filtered(
                    lambda quant: quant.location_id.usage == 'internal' and quant.quantity > 0
                ).mapped('product_id')
                line.source_product_id = products if len(products) == 1 else False

    @api.onchange('source_qty')
    def _onchange_source_qty(self):
        for line in self:
            if line.source_qty > 0:
                line.destination_qty = line.source_qty

    @api.onchange('destination_product_id')
    def _onchange_destination_product_id(self):
        for line in self:
            if line.sale_line_id.product_id != line.destination_product_id:
                line.sale_line_id = False

    @api.constrains('source_qty', 'destination_qty')
    def _check_positive_quantities(self):
        for line in self:
            if line.source_qty <= 0 or line.destination_qty <= 0:
                raise ValidationError(_('Rework quantities must be greater than zero.'))

    @api.constrains('source_product_id', 'destination_product_id')
    def _check_different_products(self):
        for line in self:
            if line.source_product_id == line.destination_product_id:
                raise ValidationError(_('The source product and result product must be different.'))

    @api.constrains('source_location_id', 'destination_location_id')
    def _check_same_package_location(self):
        for line in self:
            if (
                line.source_location_id
                and line.destination_location_id
                and line.source_location_id != line.destination_location_id
            ):
                raise ValidationError(_(
                    'The result location must match the source location because Rework keeps '
                    'both products in the same physical package.'
                ))

    @api.constrains('rework_order_id', 'sale_line_id', 'destination_product_id')
    def _check_sale_line(self):
        for line in self:
            if line.sale_line_id.order_id != line.sale_order_id:
                raise ValidationError(_('The Sale Order line must belong to the Rework Sale Order.'))
            if line.sale_line_id.product_id != line.destination_product_id:
                raise ValidationError(_('The Sale Order line product must be the Rework result product.'))

    def _check_configuration(self):
        for line in self:
            if not line.source_import_lot_id and not line.source_package_id:
                raise UserError(_(
                    'Select a source PO / future package on every Rework line.'
                ))
            if line.source_import_lot_id:
                if line.source_import_lot_id.company_id != line.company_id:
                    raise UserError(_('The source Import Lot belongs to another company.'))
                if not line.source_import_lot_id.purchase_order_id:
                    raise UserError(_(
                        'Source Import Lot %s is not linked to a Purchase Order.'
                    ) % line.source_import_lot_id.name)
                if line.source_import_lot_id.state == 'cancelled':
                    raise UserError(_(
                        'Source Import Lot %s is cancelled.'
                    ) % line.source_import_lot_id.name)
                if line.source_product_id not in line.source_import_lot_id.line_ids.mapped('product_id'):
                    raise UserError(_(
                        'Product %(product)s is not expected in source Import Lot %(lot)s.'
                    ) % {
                        'product': line.source_product_id.display_name,
                        'lot': line.source_import_lot_id.name,
                    })
            if line.source_product_id.tracking != 'none' or line.destination_product_id.tracking != 'none':
                raise UserError(_(
                    'This Rework flow requires source and result products with No Tracking. '
                    'Package tracking is supported; serial/lot tracking is not.'
                ))
            if (
                line.source_package_id.location_id
                and line.source_location_id
                and line.source_package_id.location_id != line.source_location_id
            ):
                raise UserError(_(
                    'Source package %(package)s is located in %(actual)s instead of %(expected)s.'
                ) % {
                    'package': line.source_package_id.name,
                    'actual': line.source_package_id.location_id.display_name,
                    'expected': line.source_location_id.display_name,
                })
            if float_compare(
                line.sale_line_id.qty_delivered,
                0.0,
                precision_rounding=line.sale_line_id.product_uom.rounding or 0.01,
            ) > 0:
                raise UserError(_(
                    'Sale Order line %s already has delivered quantity.'
                ) % line.sale_line_id.display_name)
            delivery_moves_with_done_qty = line.sale_line_id.move_ids.filtered(
                lambda move: move.state not in ('done', 'cancel')
                and move.picking_type_id.code == 'outgoing'
                and float_compare(
                    move.quantity_done,
                    0.0,
                    precision_rounding=move.product_uom.rounding or 0.01,
                ) > 0
            )
            if delivery_moves_with_done_qty:
                raise UserError(_(
                    'Sale Order line %s already has quantities entered on its delivery.'
                ) % line.sale_line_id.display_name)

    def _prepare_physical_source_package(self):
        self.ensure_one()
        package = self.source_package_id
        location = package.location_id
        if self.source_import_lot_id:
            expected = self.source_import_lot_id._ensure_expected_package()
            if not expected:
                raise UserError(_(
                    'Source Import Lot %s does not have a future package reference.'
                ) % self.source_import_lot_id.name)
            package = expected._get_or_create_physical_package()
            location = package.location_id or expected.expected_location_id
        if not package:
            raise UserError(_('The physical source package could not be created.'))
        self.with_context(allow_rework_line_update=True).write({
            'source_package_id': package.id,
            'source_location_id': location.id,
            'destination_location_id': location.id,
        })
        return package

    def _create_output_import_lot(self):
        self.ensure_one()
        output_lot = self.env['import.lot'].create({
            'name': '%s-%03d' % (self.rework_order_id.name, self.id),
            'expected_date': fields.Datetime.now(),
            'company_id': self.company_id.id,
            'restricted_sale_order_id': self.sale_order_id.id,
            'source_package_id': self.source_package_id.id,
            'state': 'confirmed',
        })
        output_line = self.env['import.lot.line'].create({
            'import_lot_id': output_lot.id,
            'product_id': self.destination_product_id.id,
            'product_uom_id': self.destination_uom_id.id,
            'expected_qty': self.destination_qty,
            'manual_received_qty': 0.0,
        })
        self.with_context(allow_rework_line_update=True).write({
            'output_import_lot_id': output_lot.id,
            'output_import_lot_line_id': output_line.id,
        })
        return output_lot

    def _create_output_allocation(self, output_lot):
        self.ensure_one()
        allocation = self.allocation_id.exists() or output_lot.allocation_ids.filtered(
            lambda record: record.sale_line_id == self.sale_line_id
        )
        if not allocation:
            allocation = self.env['import.lot.allocation'].create({
                'import_lot_id': output_lot.id,
                'import_lot_line_id': self.output_import_lot_line_id.id or output_lot.line_ids.id,
                'sale_line_id': self.sale_line_id.id,
                'allocated_qty': self.destination_qty,
                'state': 'reserved',
                'auto_from_sale_line': False,
                'note': _('Rework allocation from %(rework)s, line %(line)s.') % {
                    'rework': self.rework_order_id.name,
                    'line': self.sequence,
                },
            })
            self.with_context(allow_rework_line_update=True).allocation_id = allocation.id
        return allocation

    def _sync_partial_plan_to_sale_moves(self):
        Move = self.env['stock.move']
        for line in self:
            if not line.output_import_lot_id or line.state not in ('confirmed', 'done'):
                continue
            allocation = line.output_import_lot_id.allocation_ids.filtered(
                lambda record: record.sale_line_id == line.sale_line_id
                and record.state in ACTIVE_ALLOCATION_STATES
            )
            if not allocation:
                continue
            if line.sale_line_id.import_lot_id == line.output_import_lot_id:
                continue

            plan = self.env['stock.package.plan']._get_or_create_for_import_lot(
                line.sale_order_id,
                line.output_import_lot_id,
            )
            if plan.source_package_id != line.source_package_id:
                plan.source_package_id = line.source_package_id.id
            target_product_qty = line.destination_uom_id._compute_quantity(
                line.destination_qty,
                line.destination_product_id.uom_id,
                round=False,
            )
            planned_moves = line.sale_line_id.move_ids.filtered(
                lambda move: move.state != 'cancel'
                and move.picking_type_id.code == 'outgoing'
                and move.planned_package_id == plan
            )
            remaining_product_qty = target_product_qty - sum(planned_moves.mapped('product_qty'))
            precision = line.destination_product_id.uom_id.rounding or 0.01
            if float_compare(remaining_product_qty, 0.0, precision_rounding=precision) <= 0:
                continue

            candidate_moves = line.sale_line_id.move_ids.filtered(
                lambda move: move.state not in ('done', 'cancel')
                and move.picking_type_id.code == 'outgoing'
                and not move.planned_package_id
            ).sorted('id')
            normal_moves_to_reassign = Move
            plan_moves_to_reassign = Move
            for move in candidate_moves:
                if float_compare(remaining_product_qty, 0.0, precision_rounding=precision) <= 0:
                    break
                move_product_qty = move.product_qty
                if float_compare(move_product_qty, 0.0, precision_rounding=precision) <= 0:
                    continue
                if move.move_line_ids:
                    move._do_unreserve()
                if float_compare(
                    move_product_qty,
                    remaining_product_qty,
                    precision_rounding=precision,
                ) <= 0:
                    move.planned_package_id = plan.id
                    plan_moves_to_reassign |= move
                    remaining_product_qty -= move_product_qty
                    continue
                split_values = move._split(remaining_product_qty)
                for values in split_values:
                    values['planned_package_id'] = plan.id
                split_moves = Move.create(split_values)
                split_moves._action_confirm(merge=False)
                plan_moves_to_reassign |= split_moves
                normal_moves_to_reassign |= move
                remaining_product_qty = 0.0

            if (
                float_compare(remaining_product_qty, 0.0, precision_rounding=precision) > 0
                and line.sale_order_id.state in ('sale', 'done')
            ):
                raise UserError(_(
                    'The open delivery moves for Sale Order line %(line)s do not have '
                    '%(qty)s %(uom)s available for Rework %(rework)s.'
                ) % {
                    'line': line.sale_line_id.display_name,
                    'qty': remaining_product_qty,
                    'uom': line.destination_product_id.uom_id.name,
                    'rework': line.rework_order_id.name,
                })
            if normal_moves_to_reassign:
                normal_moves_to_reassign._action_assign()
            if plan.source_package_id and plan_moves_to_reassign:
                plan_moves_to_reassign._action_assign()

    def _check_source_availability(self):
        Quant = self.env['stock.quant']
        grouped_lines = {}
        for line in self:
            package = line.source_package_id
            location = package.location_id
            if not package or not location or location.usage != 'internal':
                raise UserError(_(
                    'Future package %(package)s has not been received yet. '
                    'Validate its Purchase receipt before processing the Rework.'
                ) % {
                    'package': line.source_expected_package_id.name
                    or package.name
                    or line.source_import_lot_id.name,
                })
            key = (package.id, line.source_product_id.id, location.id)
            grouped_lines[key] = grouped_lines.get(
                key,
                self.env['stock.rework.line'],
            ) | line

        for (package_id, product_id, location_id), lines in grouped_lines.items():
            package = self.env['stock.quant.package'].browse(package_id)
            product = self.env['product.product'].browse(product_id)
            location = self.env['stock.location'].browse(location_id)
            available = Quant._get_available_quantity(
                product,
                location,
                package_id=package,
                strict=True,
            )
            requested = sum(lines.mapped('source_qty'))
            if float_compare(
                available,
                requested,
                precision_rounding=product.uom_id.rounding or 0.01,
            ) < 0:
                raise UserError(_(
                    'Package %(package)s does not have enough available %(product)s in %(location)s.\n'
                    'Available: %(available)s %(uom)s\nRequested: %(requested)s %(uom)s'
                ) % {
                    'package': package.name,
                    'product': product.display_name,
                    'location': location.display_name,
                    'available': available,
                    'requested': requested,
                    'uom': product.uom_id.name,
                })

    def _create_done_move(self, product, quantity, location, location_dest, package=False, result_package=False):
        self.ensure_one()
        move = self.env['stock.move'].create({
            'name': '%s / %s' % (self.rework_order_id.name, product.display_name),
            'origin': self.rework_order_id.name,
            'product_id': product.id,
            'product_uom_qty': quantity,
            'product_uom': product.uom_id.id,
            'location_id': location.id,
            'location_dest_id': location_dest.id,
            'company_id': self.company_id.id,
            'rework_order_id': self.rework_order_id.id,
            'rework_line_id': self.id,
        })
        move._action_confirm(merge=False)
        remaining_qty = quantity
        for move_line in move.move_line_ids:
            qty_line = min(move_line.reserved_uom_qty or remaining_qty, remaining_qty)
            values = {'qty_done': qty_line}
            if package:
                values['package_id'] = package.id
            if result_package:
                values['result_package_id'] = result_package.id
            move_line.write(values)
            remaining_qty -= qty_line
            if float_compare(
                remaining_qty,
                0.0,
                precision_rounding=product.uom_id.rounding or 0.01,
            ) <= 0:
                break
        if float_compare(
            remaining_qty,
            0.0,
            precision_rounding=product.uom_id.rounding or 0.01,
        ) > 0:
            self.env['stock.move.line'].create({
                'move_id': move.id,
                'product_id': product.id,
                'product_uom_id': product.uom_id.id,
                'location_id': location.id,
                'location_dest_id': location_dest.id,
                'qty_done': remaining_qty,
                'package_id': package.id if package else False,
                'result_package_id': result_package.id if result_package else False,
                'company_id': self.company_id.id,
            })
        move._action_done()
        return move

    def _process_conversion(self):
        self.ensure_one()
        package = self.source_package_id
        stock_location = package.location_id
        production_location = self.destination_product_id.with_company(
            self.company_id
        ).property_stock_production
        if not production_location:
            raise UserError(_('No production location is configured for the company.'))

        consume_move = self._create_done_move(
            self.source_product_id,
            self.source_qty,
            stock_location,
            production_location,
            package=package,
        )
        produce_move = self._create_done_move(
            self.destination_product_id,
            self.destination_qty,
            production_location,
            stock_location,
            result_package=package,
        )
        self.with_context(allow_rework_line_update=True).write({
            'source_location_id': stock_location.id,
            'destination_location_id': stock_location.id,
            'result_package_id': package.id,
            'consume_move_id': consume_move.id,
            'produce_move_id': produce_move.id,
        })
        self.output_import_lot_line_id.write({
            'manual_received_qty': self.destination_qty,
        })
        self.output_import_lot_id.write({
            'state': 'received',
            'source_package_id': package.id,
        })
        self.allocation_id.filtered(
            lambda allocation: allocation.state == 'reserved'
        ).write({'state': 'received'})
        plans = self.env['stock.package.plan'].search([
            ('import_lot_id', '=', self.output_import_lot_id.id),
        ])
        plans.write({'source_package_id': package.id})
        plans.mapped('move_ids').filtered(
            lambda move: move.state in ('confirmed', 'waiting', 'partially_available')
        )._action_assign()

    def unlink(self):
        if self.filtered(lambda line: line.state not in ('draft', 'cancelled')):
            raise UserError(_('Rework lines can only be deleted while the Rework is in draft.'))
        return super().unlink()


class StockMove(models.Model):
    _inherit = 'stock.move'

    rework_order_id = fields.Many2one(
        'stock.rework.order',
        string='Rework Order',
        copy=False,
        readonly=True,
        ondelete='restrict',
        index=True,
    )
    rework_line_id = fields.Many2one(
        'stock.rework.line',
        string='Rework Line',
        copy=False,
        readonly=True,
        ondelete='restrict',
        index=True,
    )


class StockQuantPackage(models.Model):
    _inherit = 'stock.quant.package'

    rework_order_id = fields.Many2one(
        'stock.rework.order',
        string='Created by Rework',
        copy=False,
        readonly=True,
        ondelete='restrict',
        index=True,
    )
