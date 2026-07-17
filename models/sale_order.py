# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.tools.float_utils import float_compare


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    planned_package_ids = fields.One2many(
        'stock.package.plan',
        'sale_order_id',
        string='Planned Packages',
        copy=False,
    )
    planned_package_count = fields.Integer(
        string='Planned Packages',
        compute='_compute_planned_package_count',
    )
    import_lot_allocation_count = fields.Integer(
        string='Import Lot Allocations',
        compute='_compute_import_lot_allocation_count',
    )

    def _compute_planned_package_count(self):
        for order in self:
            order.planned_package_count = len(order.planned_package_ids)

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

    def action_view_planned_packages(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Planned Packages'),
            'res_model': 'stock.package.plan',
            'view_mode': 'tree,form',
            'domain': [('sale_order_id', '=', self.id)],
            'context': {'default_sale_order_id': self.id},
        }

    def action_confirm(self):
        res = super().action_confirm()
        for order in self:
            for line in order.order_line:
                if line.planned_package_id:
                    line._sync_planned_package_to_stock_moves()
        return res


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    import_lot_id = fields.Many2one(
        'import.lot',
        string='Import Lot',
        check_company=True,
        copy=False,
        index=True,
        help=(
            'Existing Import Lot reserved for this sale line. The commercial allocation '
            'and the internal package plan are created automatically.'
        ),
    )
    planned_package_id = fields.Many2one(
        'stock.package.plan',
        string='Planned Package',
        domain="[('sale_order_id', '=', order_id)]",
        check_company=True,
        copy=False,
        index=True,
        help='Temporary delivery package. A physical package is created only when the delivery is validated.',
    )
    # Kept for backward compatibility with the previous package-per-line version.
    package_id = fields.Many2one(
        'stock.quant.package',
        string='Legacy Source Package',
        copy=False,
        help='Deprecated physical source package field kept for existing records.',
    )
    package_available_qty = fields.Float(
        string='Available in Package',
        compute='_compute_package_available_qty',
        digits='Product Unit of Measure',
    )
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

    @api.depends('package_id', 'product_id', 'product_uom')
    def _compute_package_available_qty(self):
        Quant = self.env['stock.quant']
        for line in self:
            available = 0.0
            if line.package_id and line.product_id:
                quants = Quant.search([
                    ('product_id', '=', line.product_id.id),
                    ('package_id', '=', line.package_id.id),
                    ('location_id.usage', '=', 'internal'),
                    ('company_id', 'in', [False, line.company_id.id]),
                ])
                qty_product_uom = sum(quants.mapped('quantity'))
                available = line.product_id.uom_id._compute_quantity(
                    qty_product_uom,
                    line.product_uom or line.product_id.uom_id,
                    rounding_method='HALF-UP',
                )
            line.package_available_qty = available

    @api.depends('import_lot_allocation_ids.allocated_qty', 'import_lot_allocation_ids.state')
    def _compute_import_lot_allocation_qty(self):
        valid_states = ('reserved', 'received', 'assigned', 'done')
        for line in self:
            line.import_lot_allocated_qty = sum(
                line.import_lot_allocation_ids.filtered(lambda a: a.state in valid_states).mapped('allocated_qty')
            )

    @api.constrains('planned_package_id', 'order_id')
    def _check_planned_package_order(self):
        for line in self:
            if line.planned_package_id and line.planned_package_id.sale_order_id != line.order_id:
                raise ValidationError(_('The planned package must belong to the same Sale Order as the line.'))

    @api.constrains('import_lot_id', 'product_id', 'company_id')
    def _check_import_lot_selection(self):
        for line in self.filtered('import_lot_id'):
            if line.import_lot_id.company_id != line.company_id:
                raise ValidationError(_(
                    'The Import Lot and Sale Order line must belong to the same company.'
                ))
            if line.import_lot_id.state in ('closed', 'cancelled'):
                raise ValidationError(_(
                    'Import Lot %s is closed or cancelled and cannot be selected.'
                ) % line.import_lot_id.name)
            if line.product_id not in line.import_lot_id.line_ids.mapped('product_id'):
                raise ValidationError(_(
                    'Import Lot %(lot)s does not contain product %(product)s.'
                ) % {
                    'lot': line.import_lot_id.name,
                    'product': line.product_id.display_name,
                })

    @api.onchange('product_id')
    def _onchange_product_import_lot(self):
        for line in self:
            if (
                line.import_lot_id
                and line.product_id not in line.import_lot_id.line_ids.mapped('product_id')
            ):
                line.import_lot_id = False

    def _prepare_automatic_import_lot_allocations(self):
        """Distribute the ordered quantity across matching lines of the selected Import Lot."""
        self.ensure_one()
        lot = self.import_lot_id
        product = self.product_id
        if not lot or not product or self.product_uom_qty <= 0:
            return []

        valid_states = ('reserved', 'received', 'assigned', 'done')
        automatic_allocations = self.env['import.lot.allocation'].search([
            ('sale_line_id', '=', self.id),
            ('auto_from_sale_line', '=', True),
        ])
        remaining_product_qty = self.product_uom._compute_quantity(
            self.product_uom_qty,
            product.uom_id,
            round=False,
        )
        requested_product_qty = remaining_product_qty
        allocation_values = []

        matching_lines = lot.line_ids.filtered(lambda lot_line: lot_line.product_id == product)
        for lot_line in matching_lines:
            other_allocations = lot_line.allocation_ids.filtered(
                lambda allocation: allocation.id not in automatic_allocations.ids
                and allocation.state in valid_states
            )
            available_line_qty = max(
                lot_line.expected_qty - sum(other_allocations.mapped('allocated_qty')),
                0.0,
            )
            needed_line_qty = product.uom_id._compute_quantity(
                remaining_product_qty,
                lot_line.product_uom_id,
                round=False,
            )
            allocated_line_qty = min(available_line_qty, needed_line_qty)
            if float_compare(
                allocated_line_qty,
                0.0,
                precision_rounding=lot_line.product_uom_id.rounding or 0.01,
            ) <= 0:
                continue

            allocation_values.append({
                'import_lot_id': lot.id,
                'import_lot_line_id': lot_line.id,
                'sale_line_id': self.id,
                'allocated_qty': allocated_line_qty,
                'state': 'reserved',
                'auto_from_sale_line': True,
            })
            remaining_product_qty -= lot_line.product_uom_id._compute_quantity(
                allocated_line_qty,
                product.uom_id,
                round=False,
            )
            if float_compare(
                remaining_product_qty,
                0.0,
                precision_rounding=product.uom_id.rounding or 0.01,
            ) <= 0:
                break

        if float_compare(
            remaining_product_qty,
            0.0,
            precision_rounding=product.uom_id.rounding or 0.01,
        ) > 0:
            available_product_qty = max(requested_product_qty - remaining_product_qty, 0.0)
            available_sale_uom_qty = product.uom_id._compute_quantity(
                available_product_qty,
                self.product_uom,
                round=False,
            )
            raise ValidationError(_(
                'Import Lot %(lot)s does not have enough available-to-promise quantity for %(product)s.\n'
                'Available: %(available)s %(uom)s\nRequested: %(requested)s %(uom)s'
            ) % {
                'lot': lot.name,
                'product': product.display_name,
                'available': available_sale_uom_qty,
                'requested': self.product_uom_qty,
                'uom': self.product_uom.name,
            })

        return allocation_values

    def _sync_import_lot_selection(self):
        """Keep allocation and delivery plan in sync with the Sale Order line selection."""
        Allocation = self.env['import.lot.allocation']
        Plan = self.env['stock.package.plan']
        for line in self:
            previous_plan = line.planned_package_id
            automatic_allocations = Allocation.search([
                ('sale_line_id', '=', line.id),
                ('auto_from_sale_line', '=', True),
            ])
            allocation_values = line._prepare_automatic_import_lot_allocations()

            automatic_allocations.unlink()
            if allocation_values:
                Allocation.create(allocation_values)

            if line.import_lot_id and allocation_values:
                plan = Plan._get_or_create_for_import_lot(line.order_id, line.import_lot_id)
                if line.planned_package_id != plan:
                    line.with_context(skip_import_lot_selection_sync=True).write({
                        'planned_package_id': plan.id,
                    })
            elif line.planned_package_id and line.planned_package_id.import_lot_id:
                line.with_context(skip_import_lot_selection_sync=True).write({
                    'planned_package_id': False,
                })

            if previous_plan != line.planned_package_id:
                previous_plan._unlink_if_unused_automatic()

    def _sync_planned_package_to_stock_moves(self):
        for line in self:
            moves = line.move_ids.filtered(lambda move: move.state not in ('done', 'cancel'))
            if moves:
                moves.write({
                    'planned_package_id': line.planned_package_id.id if line.planned_package_id else False,
                })

    def _sync_package_to_stock_moves(self):
        for line in self:
            moves = line.move_ids.filtered(lambda m: m.state not in ('done', 'cancel'))
            if moves:
                moves.write({'package_id': line.package_id.id if line.package_id else False})

    def write(self, vals):
        res = super().write(vals)
        if (
            not self.env.context.get('skip_import_lot_selection_sync')
            and {'import_lot_id', 'product_id', 'product_uom_qty', 'product_uom', 'order_id'}.intersection(vals)
        ):
            self._sync_import_lot_selection()
        if 'planned_package_id' in vals:
            self._sync_planned_package_to_stock_moves()
        if 'package_id' in vals:
            self._sync_package_to_stock_moves()
        return res

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines.filtered('import_lot_id')._sync_import_lot_selection()
        return lines

    def unlink(self):
        automatic_plans = self.mapped('planned_package_id').filtered('import_lot_id')
        self.env['import.lot.allocation'].search([
            ('sale_line_id', 'in', self.ids),
            ('auto_from_sale_line', '=', True),
        ]).unlink()
        result = super().unlink()
        automatic_plans._unlink_if_unused_automatic()
        return result

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
