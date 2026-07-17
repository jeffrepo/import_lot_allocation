# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class StockPackagePlan(models.Model):
    _name = 'stock.package.plan'
    _description = 'Planned Delivery Package'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(
        string='Reference',
        required=True,
        copy=False,
        index=True,
        tracking=True,
        default=lambda self: self.env['ir.sequence'].next_by_code('stock.package.plan') or _('New'),
    )
    sale_order_id = fields.Many2one(
        'sale.order',
        string='Sale Order',
        required=True,
        ondelete='cascade',
        index=True,
        tracking=True,
    )
    import_lot_id = fields.Many2one(
        'import.lot',
        string='Import Lot',
        ondelete='restrict',
        check_company=True,
        copy=False,
        index=True,
        tracking=True,
        help='Import Lot selected on the Sale Order lines. This plan is created automatically.',
    )
    company_id = fields.Many2one(
        related='sale_order_id.company_id',
        store=True,
        index=True,
    )
    partner_id = fields.Many2one(
        related='sale_order_id.partner_id',
        string='Customer',
        store=True,
        index=True,
    )
    package_type_id = fields.Many2one(
        'stock.package.type',
        string='Package Type',
        check_company=True,
        tracking=True,
    )
    sale_line_ids = fields.One2many(
        'sale.order.line',
        'planned_package_id',
        string='Sale Order Lines',
    )
    move_ids = fields.One2many(
        'stock.move',
        'planned_package_id',
        string='Stock Moves',
        readonly=True,
    )
    real_package_ids = fields.One2many(
        'stock.quant.package',
        'planned_package_id',
        string='Physical Packages',
        readonly=True,
    )
    real_package_count = fields.Integer(
        string='Physical Packages',
        compute='_compute_real_package_count',
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('in_progress', 'Partially Delivered'),
        ('done', 'Completed'),
        ('cancelled', 'Cancelled'),
    ], string='Status', compute='_compute_state', store=True, tracking=True)
    note = fields.Text(string='Notes')

    _sql_constraints = [
        (
            'name_company_uniq',
            'unique(name, company_id)',
            'The planned package reference must be unique per company.',
        ),
        (
            'sale_order_import_lot_uniq',
            'unique(sale_order_id, import_lot_id)',
            'An Import Lot can only have one package plan per Sale Order.',
        ),
    ]

    @api.model
    def _get_or_create_for_import_lot(self, sale_order, import_lot):
        """Return the internal delivery plan for a Sale Order and Import Lot."""
        sale_order.ensure_one()
        import_lot.ensure_one()
        if sale_order.company_id != import_lot.company_id:
            raise ValidationError(_(
                'The Import Lot and Sale Order must belong to the same company.'
            ))

        plan = self.search([
            ('sale_order_id', '=', sale_order.id),
            ('import_lot_id', '=', import_lot.id),
        ], limit=1)
        if not plan:
            plan = self.create({
                'name': '%s / %s' % (import_lot.name, sale_order.name),
                'sale_order_id': sale_order.id,
                'import_lot_id': import_lot.id,
            })
        return plan

    def _unlink_if_unused_automatic(self):
        """Remove empty internal plans created from an Import Lot selection."""
        for plan in self.filtered('import_lot_id'):
            if not plan.sale_line_ids and not plan.move_ids and not plan.real_package_ids:
                plan.unlink()

    @api.depends('real_package_ids')
    def _compute_real_package_count(self):
        for plan in self:
            plan.real_package_count = len(plan.real_package_ids)

    @api.depends('sale_order_id.state', 'move_ids.state', 'real_package_ids')
    def _compute_state(self):
        for plan in self:
            if plan.sale_order_id.state == 'cancel':
                plan.state = 'cancelled'
                continue

            if plan.real_package_ids:
                open_moves = plan.move_ids.filtered(lambda move: move.state not in ('done', 'cancel'))
                plan.state = 'in_progress' if open_moves else 'done'
            elif plan.sale_order_id.state in ('sale', 'done'):
                plan.state = 'confirmed'
            else:
                plan.state = 'draft'

    @api.constrains('sale_order_id', 'import_lot_id', 'sale_line_ids', 'move_ids')
    def _check_sale_lines_order(self):
        for plan in self:
            if plan.import_lot_id and plan.import_lot_id.company_id != plan.sale_order_id.company_id:
                raise ValidationError(_(
                    'The Import Lot and Sale Order on a planned package must belong to the same company.'
                ))
            invalid_lines = plan.sale_line_ids.filtered(lambda line: line.order_id != plan.sale_order_id)
            invalid_moves = plan.move_ids.filtered(
                lambda move: move.sale_line_id and move.sale_line_id.order_id != plan.sale_order_id
            )
            if invalid_lines or invalid_moves:
                raise ValidationError(_(
                    'All Sale Order lines and stock moves in a planned package must belong to the same Sale Order.'
                ))

    def action_view_real_packages(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Physical Packages'),
            'res_model': 'stock.quant.package',
            'view_mode': 'tree,form',
            'domain': [('planned_package_id', '=', self.id)],
        }


class StockQuantPackage(models.Model):
    _inherit = 'stock.quant.package'

    planned_package_id = fields.Many2one(
        'stock.package.plan',
        string='Planned Package',
        ondelete='restrict',
        copy=False,
        index=True,
        readonly=True,
    )
    planned_picking_id = fields.Many2one(
        'stock.picking',
        string='Created for Transfer',
        ondelete='set null',
        copy=False,
        index=True,
        readonly=True,
    )
