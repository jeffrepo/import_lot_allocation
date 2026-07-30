# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare


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
    source_package_id = fields.Many2one(
        'stock.quant.package',
        string='Source Package',
        required=True,
        check_company=True,
        tracking=True,
        domain="[('location_id.usage', '=', 'internal'), '|', ('company_id', '=', False), ('company_id', '=', company_id)]",
        help='Physical package already received in stock. The Rework result remains in this same package.',
    )
    source_product_domain_ids = fields.Many2many(
        'product.product',
        string='Products in Source Package',
        compute='_compute_source_product_domain_ids',
    )
    source_product_id = fields.Many2one(
        'product.product',
        string='Source Product',
        required=True,
        tracking=True,
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
        required=True,
        check_company=True,
        tracking=True,
        domain="[('usage', '=', 'internal'), '|', ('company_id', '=', False), ('company_id', '=', company_id)]",
    )
    source_available_qty = fields.Float(
        string='Available in Source Package',
        compute='_compute_source_available_qty',
        digits='Product Unit of Measure',
    )
    source_qty = fields.Float(
        string='Quantity to Consume',
        required=True,
        default=1.0,
        digits='Product Unit of Measure',
        tracking=True,
    )
    destination_product_id = fields.Many2one(
        'product.product',
        string='Result Product',
        required=True,
        tracking=True,
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
        required=True,
        check_company=True,
        tracking=True,
        domain="[('usage', '=', 'internal'), '|', ('company_id', '=', False), ('company_id', '=', company_id)]",
        help='Must be the source location because the result stays in the same physical package.',
    )
    destination_qty = fields.Float(
        string='Quantity to Produce',
        required=True,
        default=1.0,
        digits='Product Unit of Measure',
        tracking=True,
    )
    sale_order_id = fields.Many2one(
        'sale.order',
        string='Reserved for Sale Order',
        required=True,
        check_company=True,
        tracking=True,
        domain="[('company_id', '=', company_id), ('state', 'not in', ('done', 'cancel'))]",
    )
    sale_line_id = fields.Many2one(
        'sale.order.line',
        string='Sale Order Line',
        required=True,
        tracking=True,
        domain="[('order_id', '=', sale_order_id), ('product_id', '=', destination_product_id), ('display_type', '=', False)]",
        help=(
            'If the Rework result covers only part of this line, the module automatically '
            'splits that quantity into a separate Sale Order line assigned to the Rework.'
        ),
    )
    import_lot_id = fields.Many2one(
        'import.lot',
        string='Rework Import Lot',
        copy=False,
        readonly=True,
        ondelete='restrict',
        index=True,
    )
    result_package_id = fields.Many2one(
        'stock.quant.package',
        string='Reworked Package',
        copy=False,
        readonly=True,
        ondelete='restrict',
        index=True,
        help='The original source package after the converted product has been added to it.',
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
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('done', 'Done'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, copy=False, tracking=True, index=True)
    note = fields.Text(string='Notes')

    _sql_constraints = [
        (
            'name_company_uniq',
            'unique(name, company_id)',
            'The Rework reference must be unique per company.',
        ),
        (
            'import_lot_uniq',
            'unique(import_lot_id)',
            'An Import Lot can only belong to one Rework Order.',
        ),
    ]

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

    @api.depends('source_package_id')
    def _compute_source_product_domain_ids(self):
        for rework in self:
            quants = rework.source_package_id.quant_ids.filtered(
                lambda quant: quant.location_id.usage == 'internal' and quant.quantity > 0
            )
            rework.source_product_domain_ids = quants.mapped('product_id')

    @api.depends('source_package_id', 'source_product_id', 'source_location_id')
    def _compute_source_available_qty(self):
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

    @api.onchange('source_package_id')
    def _onchange_source_package_id(self):
        for rework in self:
            rework.source_location_id = rework.source_package_id.location_id
            products = rework.source_package_id.quant_ids.filtered(
                lambda quant: quant.location_id.usage == 'internal' and quant.quantity > 0
            ).mapped('product_id')
            rework.source_product_id = products if len(products) == 1 else False
            rework.destination_location_id = rework.source_package_id.location_id

    @api.onchange('source_qty')
    def _onchange_source_qty(self):
        for rework in self:
            if rework.source_qty > 0:
                rework.destination_qty = rework.source_qty

    @api.onchange('sale_order_id')
    def _onchange_sale_order_id(self):
        for rework in self:
            if rework.sale_line_id.order_id != rework.sale_order_id:
                rework.sale_line_id = False

    @api.onchange('destination_product_id')
    def _onchange_destination_product_id(self):
        for rework in self:
            if rework.sale_line_id.product_id != rework.destination_product_id:
                rework.sale_line_id = False

    @api.constrains('source_qty', 'destination_qty')
    def _check_positive_quantities(self):
        for rework in self:
            if rework.source_qty <= 0 or rework.destination_qty <= 0:
                raise ValidationError(_('Rework quantities must be greater than zero.'))

    @api.constrains('source_product_id', 'destination_product_id')
    def _check_different_products(self):
        for rework in self:
            if rework.source_product_id == rework.destination_product_id:
                raise ValidationError(_('The source product and result product must be different.'))

    @api.constrains('source_location_id', 'destination_location_id')
    def _check_same_package_location(self):
        for rework in self:
            if (
                rework.source_location_id
                and rework.destination_location_id
                and rework.source_location_id != rework.destination_location_id
            ):
                raise ValidationError(_(
                    'The result location must match the source location because Rework keeps '
                    'the consumed and generated products in the same physical package.'
                ))

    @api.constrains('sale_order_id', 'sale_line_id', 'destination_product_id')
    def _check_sale_line(self):
        for rework in self:
            if rework.sale_line_id.order_id != rework.sale_order_id:
                raise ValidationError(_('The Sale Order line must belong to the selected Sale Order.'))
            if rework.sale_line_id.product_id != rework.destination_product_id:
                raise ValidationError(_('The Sale Order line product must be the Rework result product.'))

    def _check_can_confirm(self):
        for rework in self:
            if rework.sale_order_id.state in ('done', 'cancel'):
                raise UserError(_('The selected Sale Order is done or cancelled.'))
            if rework.source_product_id.tracking != 'none' or rework.destination_product_id.tracking != 'none':
                raise UserError(_(
                    'This Rework flow currently requires source and result products with No Tracking. '
                    'Package tracking is supported; serial/lot tracking is not.'
                ))
            if rework.source_package_id.location_id != rework.source_location_id:
                raise UserError(_(
                    'Source package %(package)s is no longer located in %(location)s. '
                    'Select the package again before processing the Rework.'
                ) % {
                    'package': rework.source_package_id.name,
                    'location': rework.source_location_id.display_name,
                })
            if rework.sale_line_id.import_lot_id and rework.sale_line_id.import_lot_id != rework.import_lot_id:
                raise UserError(_(
                    'Sale Order line %(line)s already uses Import Lot %(lot)s. Clear it before confirming this Rework.'
                ) % {
                    'line': rework.sale_line_id.display_name,
                    'lot': rework.sale_line_id.import_lot_id.name,
                })

    def _split_sale_line_for_partial_result(self):
        """Keep one physical source package per Sale Order line.

        A partial Rework cannot point the complete sale line to its package because
        the remaining quantity may come from unrestricted stock or another Import Lot.
        Split the result quantity into its own line before assigning the Rework lot.
        """
        self.ensure_one()
        sale_line = self.sale_line_id
        rework_sale_qty = self.destination_uom_id._compute_quantity(
            self.destination_qty,
            sale_line.product_uom,
            round=False,
        )
        precision = sale_line.product_uom.rounding or 0.01
        if float_compare(
            rework_sale_qty,
            sale_line.product_uom_qty,
            precision_rounding=precision,
        ) >= 0:
            return sale_line

        active_invoice_lines = sale_line.invoice_lines.filtered(
            lambda invoice_line: invoice_line.move_id.state != 'cancel'
        )
        if (
            float_compare(sale_line.qty_delivered, 0.0, precision_rounding=precision) > 0
            or float_compare(sale_line.qty_invoiced, 0.0, precision_rounding=precision) > 0
            or active_invoice_lines
        ):
            raise UserError(_(
                'Sale Order line %(line)s is already delivered or invoiced and cannot be split automatically. '
                'Add a separate Sale Order line for the Rework quantity.'
            ) % {'line': sale_line.display_name})

        remaining_qty = sale_line.product_uom_qty - rework_sale_qty
        sale_line.write({'product_uom_qty': remaining_qty})
        rework_line = sale_line.copy(default={
            'sequence': sale_line.sequence + 1,
            'product_uom_qty': rework_sale_qty,
            'import_lot_id': False,
            'planned_package_id': False,
            'package_id': False,
        })
        self.sale_line_id = rework_line.id
        return rework_line

    def _create_rework_import_lot(self):
        self.ensure_one()
        import_lot = self.env['import.lot'].create({
            'name': self.name,
            'expected_date': fields.Datetime.now(),
            'company_id': self.company_id.id,
            'restricted_sale_order_id': self.sale_order_id.id,
            'state': 'confirmed',
        })
        self.env['import.lot.line'].create({
            'import_lot_id': import_lot.id,
            'product_id': self.destination_product_id.id,
            'product_uom_id': self.destination_uom_id.id,
            'expected_qty': self.destination_qty,
            'manual_received_qty': 0.0,
        })
        self.import_lot_id = import_lot.id
        return import_lot

    def action_confirm(self):
        for rework in self:
            if rework.state != 'draft':
                continue
            rework._split_sale_line_for_partial_result()
            rework._check_can_confirm()
            import_lot = rework.import_lot_id or rework._create_rework_import_lot()
            rework.sale_line_id.import_lot_id = import_lot.id
            rework.state = 'confirmed'
        return True

    def _check_source_availability(self):
        Quant = self.env['stock.quant']
        for rework in self:
            available = Quant._get_available_quantity(
                rework.source_product_id,
                rework.source_location_id,
                package_id=rework.source_package_id,
                strict=True,
            )
            if float_compare(
                available,
                rework.source_qty,
                precision_rounding=rework.source_uom_id.rounding or 0.01,
            ) < 0:
                raise UserError(_(
                    'Package %(package)s does not have enough available %(product)s in %(location)s.\n'
                    'Available: %(available)s %(uom)s\nRequested: %(requested)s %(uom)s'
                ) % {
                    'package': rework.source_package_id.name,
                    'product': rework.source_product_id.display_name,
                    'location': rework.source_location_id.display_name,
                    'available': available,
                    'requested': rework.source_qty,
                    'uom': rework.source_uom_id.name,
                })

    def _create_done_move(self, product, quantity, location, location_dest, package=False, result_package=False):
        self.ensure_one()
        move = self.env['stock.move'].create({
            'name': self.name,
            'origin': self.name,
            'product_id': product.id,
            'product_uom_qty': quantity,
            'product_uom': product.uom_id.id,
            'location_id': location.id,
            'location_dest_id': location_dest.id,
            'company_id': self.company_id.id,
            'rework_order_id': self.id,
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

    def action_process(self):
        for rework in self:
            if rework.state == 'draft':
                rework.action_confirm()
            if rework.state != 'confirmed':
                continue

            rework._check_can_confirm()
            rework._check_source_availability()
            production_location = rework.destination_product_id.with_company(
                rework.company_id
            ).property_stock_production
            if not production_location:
                raise UserError(_('No production location is configured for the company.'))

            # Rework is a partial conversion inside one physical package. The source
            # quantity is consumed and the generated product is put back into that
            # same package; no second package is created.
            result_package = rework.source_package_id
            consume_move = rework._create_done_move(
                rework.source_product_id,
                rework.source_qty,
                rework.source_location_id,
                production_location,
                package=rework.source_package_id,
            )
            produce_move = rework._create_done_move(
                rework.destination_product_id,
                rework.destination_qty,
                production_location,
                rework.destination_location_id,
                result_package=result_package,
            )

            rework.write({
                'result_package_id': result_package.id,
                'consume_move_id': consume_move.id,
                'produce_move_id': produce_move.id,
                'state': 'done',
            })
            rework.import_lot_id.line_ids.write({
                'manual_received_qty': rework.destination_qty,
            })
            rework.import_lot_id.write({
                'state': 'received',
                'source_package_id': result_package.id,
            })
            rework.import_lot_id.allocation_ids.filtered(
                lambda allocation: allocation.state == 'reserved'
            ).write({'state': 'received'})

            plans = self.env['stock.package.plan'].search([
                ('import_lot_id', '=', rework.import_lot_id.id),
            ])
            plans.write({'source_package_id': result_package.id})
            plans.mapped('move_ids').filtered(
                lambda move: move.state in ('confirmed', 'waiting', 'partially_available')
            )._action_assign()
        return True

    def action_cancel(self):
        for rework in self:
            if rework.state == 'done':
                raise UserError(_(
                    'A completed Rework cannot be cancelled because stock has already moved. '
                    'Create a reverse Rework if you need to undo it.'
                ))
            if rework.import_lot_id:
                sale_lines = self.env['sale.order.line'].search([
                    ('import_lot_id', '=', rework.import_lot_id.id),
                ])
                sale_lines.write({'import_lot_id': False})
                rework.import_lot_id.state = 'cancelled'
            rework.state = 'cancelled'
        return True

    def action_view_import_lot(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Rework Import Lot'),
            'res_model': 'import.lot',
            'view_mode': 'form',
            'res_id': self.import_lot_id.id,
        }

    def action_view_result_package(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Reworked Package'),
            'res_model': 'stock.quant.package',
            'view_mode': 'form',
            'res_id': self.result_package_id.id,
        }

    def action_view_moves(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Rework Stock Moves'),
            'res_model': 'stock.move',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', (self.consume_move_id | self.produce_move_id).ids)],
        }

    def unlink(self):
        if self.filtered(lambda rework: rework.state not in ('draft', 'cancelled')):
            raise UserError(_('Only draft or cancelled Rework Orders can be deleted.'))
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
