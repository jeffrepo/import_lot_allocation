# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.tools.float_utils import float_compare, float_round


class ImportLot(models.Model):
    _name = 'import.lot'
    _description = 'Import / Supply Lot'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'expected_date desc, id desc'

    name = fields.Char(
        string='Reference',
        required=True,
        copy=False,
        index=True,
        tracking=True,
        default=lambda self: self.env['ir.sequence'].next_by_code('import.lot') or _('New'),
        help='Main commercial reference. When created from a purchase order, it uses the PO number.',
    )
    purchase_order_id = fields.Many2one(
        'purchase.order',
        string='Purchase Order',
        index=True,
        tracking=True,
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Vendor',
        related='purchase_order_id.partner_id',
        store=True,
        readonly=False,
    )
    expected_date = fields.Datetime(
        string='Expected Date',
        tracking=True,
    )
    line_ids = fields.One2many(
        'import.lot.line',
        'import_lot_id',
        string='Expected Lines',
        copy=True,
    )
    allocation_ids = fields.One2many(
        'import.lot.allocation',
        'import_lot_id',
        string='Allocations',
    )
    picking_ids = fields.One2many(
        'stock.picking',
        'import_lot_id',
        string='Receipts / Transfers',
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
        index=True,
    )
    currency_id = fields.Many2one(
        related='company_id.currency_id',
        store=True,
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('in_transit', 'In Transit'),
        ('partially_received', 'Partially Received'),
        ('received', 'Received'),
        ('closed', 'Closed'),
        ('cancelled', 'Cancelled'),
        ('exception', 'Exception'),
    ], string='Status', default='draft', tracking=True, index=True)

    expected_qty = fields.Float(
        string='Expected Qty',
        compute='_compute_totals',
        store=True,
    )
    allocated_qty = fields.Float(
        string='Allocated Qty',
        compute='_compute_totals',
        store=True,
    )
    received_qty = fields.Float(
        string='Received Qty',
        compute='_compute_totals',
        store=True,
    )
    available_to_promise_qty = fields.Float(
        string='Available to Promise',
        compute='_compute_totals',
        store=True,
    )
    allocation_count = fields.Integer(
        string='Allocation Count',
        compute='_compute_counts',
    )
    picking_count = fields.Integer(
        string='Picking Count',
        compute='_compute_counts',
    )

    @api.depends('line_ids.expected_qty', 'line_ids.allocated_qty', 'line_ids.received_qty', 'line_ids.available_to_promise_qty')
    def _compute_totals(self):
        for lot in self:
            lot.expected_qty = sum(lot.line_ids.mapped('expected_qty'))
            lot.allocated_qty = sum(lot.line_ids.mapped('allocated_qty'))
            lot.received_qty = sum(lot.line_ids.mapped('received_qty'))
            lot.available_to_promise_qty = sum(lot.line_ids.mapped('available_to_promise_qty'))

    def _compute_counts(self):
        for lot in self:
            lot.allocation_count = len(lot.allocation_ids)
            lot.picking_count = len(lot.picking_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('purchase_order_id') and (not vals.get('name') or vals.get('name') == _('New')):
                po = self.env['purchase.order'].browse(vals['purchase_order_id'])
                vals['name'] = self._get_name_from_purchase_order(po)
        return super().create(vals_list)

    def _get_name_from_purchase_order(self, purchase_order):
        """Use the PO number as the main Import Lot reference.

        If an Import Lot already exists for the PO, append -LXX to avoid duplicate names.
        """
        base_name = purchase_order.name
        existing = self.search_count([('name', '=', base_name), ('company_id', '=', purchase_order.company_id.id)])
        if not existing:
            return base_name
        seq = existing + 1
        while True:
            candidate = '%s-L%02d' % (base_name, seq)
            if not self.search_count([('name', '=', candidate), ('company_id', '=', purchase_order.company_id.id)]):
                return candidate
            seq += 1

    def action_confirm(self):
        self.write({'state': 'confirmed'})

    def action_set_in_transit(self):
        self.write({'state': 'in_transit'})

    def action_close(self):
        self.write({'state': 'closed'})

    def action_cancel(self):
        self.write({'state': 'cancelled'})

    def action_view_allocations(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Import Lot Allocations'),
            'res_model': 'import.lot.allocation',
            'view_mode': 'tree,form',
            'domain': [('import_lot_id', '=', self.id)],
            'context': {'default_import_lot_id': self.id},
        }

    def action_view_pickings(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Import Lot Transfers'),
            'res_model': 'stock.picking',
            'view_mode': 'tree,form',
            'domain': [('import_lot_id', '=', self.id)],
            'context': {'default_import_lot_id': self.id},
        }


class ImportLotLine(models.Model):
    _name = 'import.lot.line'
    _description = 'Import Lot Expected Line'
    _order = 'import_lot_id, id'

    import_lot_id = fields.Many2one(
        'import.lot',
        string='Import Lot',
        required=True,
        ondelete='cascade',
        index=True,
    )
    purchase_line_id = fields.Many2one(
        'purchase.order.line',
        string='Purchase Order Line',
        index=True,
    )
    product_id = fields.Many2one(
        'product.product',
        string='Product',
        required=True,
        index=True,
    )
    product_uom_id = fields.Many2one(
        'uom.uom',
        string='UoM',
        required=True,
    )
    expected_qty = fields.Float(
        string='Expected Qty',
        digits='Product Unit of Measure',
        required=True,
        default=0.0,
    )
    received_qty = fields.Float(
        string='Received Qty',
        digits='Product Unit of Measure',
        compute='_compute_received_qty',
        store=True,
        readonly=False,
    )
    allocation_ids = fields.One2many(
        'import.lot.allocation',
        'import_lot_line_id',
        string='Allocations',
    )
    allocated_qty = fields.Float(
        string='Allocated Qty',
        digits='Product Unit of Measure',
        compute='_compute_allocated_qty',
        store=True,
    )
    available_to_promise_qty = fields.Float(
        string='Available to Promise',
        digits='Product Unit of Measure',
        compute='_compute_available_to_promise_qty',
        store=True,
    )
    company_id = fields.Many2one(
        related='import_lot_id.company_id',
        store=True,
    )
    state = fields.Selection(
        related='import_lot_id.state',
        store=True,
    )

    @api.onchange('purchase_line_id')
    def _onchange_purchase_line_id(self):
        for line in self:
            if line.purchase_line_id:
                pol = line.purchase_line_id
                line.product_id = pol.product_id
                line.product_uom_id = pol.product_uom
                line.expected_qty = pol.product_qty

    @api.depends('purchase_line_id.qty_received')
    def _compute_received_qty(self):
        for line in self:
            if line.purchase_line_id:
                line.received_qty = line.purchase_line_id.qty_received

    @api.depends('allocation_ids.allocated_qty', 'allocation_ids.state')
    def _compute_allocated_qty(self):
        valid_states = ('reserved', 'received', 'assigned', 'done')
        for line in self:
            line.allocated_qty = sum(line.allocation_ids.filtered(lambda a: a.state in valid_states).mapped('allocated_qty'))

    @api.depends('expected_qty', 'allocated_qty')
    def _compute_available_to_promise_qty(self):
        for line in self:
            line.available_to_promise_qty = line.expected_qty - line.allocated_qty

    @api.constrains('expected_qty')
    def _check_expected_qty(self):
        for line in self:
            if line.expected_qty < 0:
                raise ValidationError(_('Expected quantity cannot be negative.'))


class ImportLotAllocation(models.Model):
    _name = 'import.lot.allocation'
    _description = 'Import Lot Allocation'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'priority, expected_date, id'

    name = fields.Char(
        string='Reference',
        compute='_compute_name',
        store=True,
    )
    import_lot_id = fields.Many2one(
        'import.lot',
        string='Import Lot',
        required=True,
        index=True,
        ondelete='cascade',
        tracking=True,
    )
    import_lot_line_id = fields.Many2one(
        'import.lot.line',
        string='Import Lot Line',
        required=True,
        index=True,
        domain="[('import_lot_id', '=', import_lot_id)]",
    )
    sale_order_id = fields.Many2one(
        'sale.order',
        string='Sale Order',
        related='sale_line_id.order_id',
        store=True,
        index=True,
    )
    sale_line_id = fields.Many2one(
        'sale.order.line',
        string='Sale Order Line',
        required=True,
        index=True,
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Customer',
        related='sale_order_id.partner_id',
        store=True,
        index=True,
    )
    product_id = fields.Many2one(
        'product.product',
        string='Product',
        related='import_lot_line_id.product_id',
        store=True,
        readonly=True,
    )
    product_uom_id = fields.Many2one(
        'uom.uom',
        string='UoM',
        related='import_lot_line_id.product_uom_id',
        store=True,
        readonly=True,
    )
    allocated_qty = fields.Float(
        string='Allocated Qty',
        digits='Product Unit of Measure',
        required=True,
        default=0.0,
        tracking=True,
    )
    received_qty = fields.Float(
        string='Received Qty',
        digits='Product Unit of Measure',
        compute='_compute_quantities',
        store=True,
    )
    assigned_qty = fields.Float(
        string='Assigned Qty',
        digits='Product Unit of Measure',
        default=0.0,
        tracking=True,
        help='Physical quantity assigned to the outgoing picking once the stock exists.',
    )
    delivered_qty = fields.Float(
        string='Delivered Qty',
        digits='Product Unit of Measure',
        compute='_compute_delivered_qty',
        store=True,
    )
    pending_qty = fields.Float(
        string='Pending Qty',
        digits='Product Unit of Measure',
        compute='_compute_quantities',
        store=True,
    )
    purchase_order_id = fields.Many2one(
        'purchase.order',
        string='Purchase Order',
        related='import_lot_id.purchase_order_id',
        store=True,
        index=True,
    )
    purchase_line_id = fields.Many2one(
        'purchase.order.line',
        string='Purchase Order Line',
        related='import_lot_line_id.purchase_line_id',
        store=True,
        readonly=True,
    )
    incoming_picking_id = fields.Many2one(
        'stock.picking',
        string='Incoming Picking',
        domain="[('picking_type_code', '=', 'incoming')]",
    )
    outgoing_picking_id = fields.Many2one(
        'stock.picking',
        string='Outgoing Picking',
        domain="[('picking_type_code', '=', 'outgoing')]",
    )
    expected_date = fields.Datetime(
        string='Expected Date',
        related='import_lot_id.expected_date',
        store=True,
    )
    priority = fields.Integer(
        string='Priority',
        default=10,
        help='Lower number means higher priority when allocating received stock.',
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('reserved', 'Reserved'),
        ('received', 'Received'),
        ('assigned', 'Assigned to Picking'),
        ('done', 'Done'),
        ('cancelled', 'Cancelled'),
        ('exception', 'Exception'),
    ], string='Status', default='reserved', tracking=True, index=True)
    company_id = fields.Many2one(
        related='import_lot_id.company_id',
        store=True,
    )
    note = fields.Text(string='Notes')

    @api.depends('import_lot_id.name', 'sale_order_id.name', 'product_id.display_name', 'allocated_qty')
    def _compute_name(self):
        for allocation in self:
            allocation.name = '%s / %s / %s' % (
                allocation.import_lot_id.name or '',
                allocation.sale_order_id.name or '',
                allocation.product_id.display_name or '',
            )

    @api.depends('allocated_qty', 'import_lot_line_id.received_qty')
    def _compute_quantities(self):
        for allocation in self:
            received = min(allocation.allocated_qty, allocation.import_lot_line_id.received_qty)
            allocation.received_qty = received
            allocation.pending_qty = max(allocation.allocated_qty - received, 0.0)

    @api.depends('sale_line_id.qty_delivered')
    def _compute_delivered_qty(self):
        for allocation in self:
            allocation.delivered_qty = min(allocation.sale_line_id.qty_delivered, allocation.allocated_qty)

    @api.onchange('import_lot_line_id')
    def _onchange_import_lot_line_id(self):
        for allocation in self:
            if allocation.import_lot_line_id:
                allocation.import_lot_id = allocation.import_lot_line_id.import_lot_id

    @api.constrains('allocated_qty')
    def _check_allocated_qty(self):
        for allocation in self:
            if allocation.allocated_qty <= 0:
                raise ValidationError(_('Allocated quantity must be greater than zero.'))

    @api.constrains('import_lot_line_id', 'sale_line_id')
    def _check_product_match(self):
        for allocation in self:
            if allocation.import_lot_line_id.product_id != allocation.sale_line_id.product_id:
                raise ValidationError(_(
                    'The Import Lot line product (%s) must match the sale line product (%s).'
                ) % (allocation.import_lot_line_id.product_id.display_name, allocation.sale_line_id.product_id.display_name))

    @api.constrains('allocated_qty', 'import_lot_line_id', 'state')
    def _check_available_to_promise(self):
        valid_states = ('reserved', 'received', 'assigned', 'done')
        for allocation in self:
            if allocation.state not in valid_states:
                continue
            line = allocation.import_lot_line_id
            other_allocations = line.allocation_ids.filtered(lambda a: a.id != allocation.id and a.state in valid_states)
            allocated_other = sum(other_allocations.mapped('allocated_qty'))
            remaining = line.expected_qty - allocated_other
            precision = allocation.product_uom_id.rounding or 0.01
            if float_compare(allocation.allocated_qty, remaining, precision_rounding=precision) > 0:
                raise ValidationError(_(
                    'Not enough available-to-promise quantity in Import Lot %(lot)s for product %(product)s.\n'
                    'Available: %(available)s %(uom)s\nRequested: %(requested)s %(uom)s'
                ) % {
                    'lot': line.import_lot_id.name,
                    'product': line.product_id.display_name,
                    'available': float_round(remaining, precision_rounding=precision),
                    'requested': allocation.allocated_qty,
                    'uom': allocation.product_uom_id.name,
                })

    def action_reserved(self):
        self.write({'state': 'reserved'})

    def action_received(self):
        self.write({'state': 'received'})

    def action_assigned(self):
        self.write({'state': 'assigned'})

    def action_done(self):
        self.write({'state': 'done'})

    def action_exception(self):
        self.write({'state': 'exception'})

    def action_cancel(self):
        self.write({'state': 'cancelled'})
